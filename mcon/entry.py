from __future__ import annotations

import os
import shutil
from abc import ABC, ABCMeta, abstractmethod
from pathlib import Path, PurePath
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    MutableSet,
    Optional,
    Set,
    Tuple,
)

if TYPE_CHECKING:
    from mcon.builder import Builder
    from mcon.environment import Environment
    from mcon.types import E, FileSetLike, StrPath


class Node(ABC):  # noqa: B024
    """Represents a node in the dependency graph"""

    def __init__(self, env: Environment):
        self.env = env

        # Which builder builds this entry
        # This builder's dependencies are implicit dependencies of this entry.
        self.builder: Optional["Builder"] = None

        # Explict nodes this node depends on and must be built before this node can be
        # built.
        self.depends: MutableSet[Node] = set()


class EntryMeta(ABCMeta):
    def __call__(
        cls,
        env: Environment,
        path: StrPath,
        *args: Tuple,
        **kwargs: Dict,
    ) -> Entry:
        # Make sure path is always absolute, interpreting relative paths as relative
        # to the environment root
        path = env.root.joinpath(path)

        # See if this entry already exists
        try:
            entry = env.execution.entries[path]
            if not isinstance(entry, cls):
                raise TypeError(
                    f"Path {path} already exists but is the wrong type. Expected "
                    f"{cls} got {type(entry)}"
                )
            for key, value in kwargs.items():
                if key not in entry.settable_attributes:
                    raise ValueError(f"Cannot set property {key} on {cls}")
                setattr(entry, key, value)
            return entry
        except KeyError:
            pass

        entry = super().__call__(env, path, *args, **kwargs)
        env.execution.entries[path] = entry
        return entry


class Entry(Node, metaclass=EntryMeta):
    """Represents a file or a directory on the filesystem with a path

    The path may or may not exist until it is built. After its builder builds it,
    the path is expected to exist.
    """

    settable_attributes: List[str] = [
        "leave",
    ]

    def __init__(self, env: "Environment", path: StrPath, *, leave: bool = False):
        super().__init__(env)
        self.path: Path = env.root.joinpath(path)
        self.leave = leave
        self.out_of_date: bool = False

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, type(self)) and self.path == other.path

    def __str__(self) -> str:
        try:
            return str(self.path.relative_to(self.env.root))
        except ValueError:
            return str(self.path)

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        rel_path = str(self)
        return f"{cls_name}({rel_path!r})"

    def relative_to(self, root: StrPath = "") -> str:
        """Returns the current file's path relative to the given root either within
        a build directory or the environment's root.

        This is different than calling file.path.relative_to() in that if the current
        file is within a build directory (env.build_root / "some_dir_name"), the
        given root parameter is taken to be relative to that build root, not to
        the environment root.

        For example, if a File has path foo/bar/baz.txt

        >>> f = File(..., "foo/bar/baz.txt")
        >>> f.relative_to("")
            "foo/bar/baz.txt"
        >>> f.relative_to("foo")
            "bar/baz.txt"

        But if the file is within a build directory, the result is the same:

        >>> f = File(..., "build/bdir/foo/bar/baz.txt")
        >>> f.relative_to("")
            "foo/bar/baz.txt"
        >>> f.relative_to("foo")
            "bar/baz.txt"

        """
        file_rel_path = self.env.get_rel_path(self.path)
        root_rel_path = self.env.get_rel_path(root)
        new_rel_path = PurePath(file_rel_path).relative_to(root_rel_path)
        return str(new_rel_path)

    def derive(self: "E", build_dir_name: StrPath, new_ext: Optional[str] = None) -> "E":
        """Create a derivative file/dir from this entry using Environment.get_build_path()"""
        new_path = self.env.get_build_path(self.path, build_dir_name, new_ext)

        return type(self)(self.env, new_path)

    def prepare(self) -> None:
        """Hook for the entry to do anything it may need to do before being built

        Called right before its builder is called.
        """
        # Make sure the parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def get_metadata(self) -> Any:
        """Returns any metadata this entry should use to compare whether it has changed"""
        ...

    @abstractmethod
    def remove(self) -> None:
        """Removes this entry from the filesystem. Called before building this entry"""
        ...


class File(Entry):
    """A file in a known location on the filesystem

    May or may not exist until built. File objects without a builder imply the file
    should exist as a prior condition to building anything. e.g. source files which aren't
    generated.
    """

    def get_metadata(self) -> Any:
        try:
            stat_result = os.stat(self.path)
        except FileNotFoundError:
            return None
        return {
            "mtime": stat_result.st_mtime_ns,
            "mode": stat_result.st_mode,
            "size": stat_result.st_size,
        }

    def remove(self) -> None:
        if not self.leave:
            self.path.unlink(missing_ok=True)


class Dir(Entry, Iterable[File]):
    """A directory of files

    The directory referred to by the Dir object may not exist until it is built.
    After building, the Dir object may be treated as a Collection of File objects, or
    treated as a single unit (moved around, passed to another builder that expects a Dir,
    etc).

    Builders which output a known set of files (either at resolution time or build time)
    should prefer to output a FileSet. Outputting a Dir may conflict with other builders
    which may want to add files to the directory. Dir targets let builders treat a
    directory as a single unit instead of a collection of files. It is commonly useful
    when calling into another build process which outputs its own directory of files and
    an mcon builder doesn't know or want to know the exact set of files.
    """

    def __init__(
        self,
        env: "Environment",
        path: StrPath,
        *,
        glob: str = "**/*",
        leave: bool = False,
    ):
        super().__init__(env, path, leave=leave)
        self.glob_pattern = glob

    def __iter__(self) -> Iterator["File"]:
        for path in self.path.glob(self.glob_pattern):
            if path.is_file():
                yield self.env.file(path)

    def get_metadata(self) -> Any:
        try:
            stat_result = os.stat(self.path)
        except FileNotFoundError:
            return None
        metadata: Dict[str, Any]
        metadata = {
            "mode": stat_result.st_mode,
            "files": {},
        }

        file_list: List["File"] = list(self)
        for file in file_list:
            file_metadata = file.get_metadata()
            metadata["files"][str(file.path)] = file_metadata
        return metadata

    def remove(self) -> None:
        if not self.leave and self.path.is_dir():
            shutil.rmtree(self.path)


class FileSet(Node, Iterable[File]):
    """A set of files whose contents is not necessarily known until build time after
    the fileset has been built.

    There are two ways a FileSet is typically used:

    1. As a build output. A Builder will create an empty fileset and register it as a target.
    Other builders will depend on it. During the build phase, the FileSet's builder will
    create a number of files and add them to the fileset. Afterwards, the dependent builders will
    have a populated fileset to iterate over. This is the typical way Builders will output
    files that aren't known until after they are built.

    2. As a build input. A Builder may use Builder.depends_files() to collect a
    number of known or unknown files together and mark them as a dependency. A
    Builder will then use these FileSets during its own build phase.

    Note: If a builder is, during the build phase, creating File and/or Dir objects in
    arbitrary locations with intent to add them to a target FileSet, the parent
    directories of those files are not automatically created (unlike with File and Dir
    targets, where .prepare() is called to create the parent directories before
    Builder.build() is called)

    """

    def __init__(self, env: Environment, sources: Optional[FileSetLike] = None):
        super().__init__(env)
        self._sources: List[Node] = []
        if sources is not None:
            self.add(sources)

    def __str__(self) -> str:
        return "Abstract FileSet"

    def add(self, sources: FileSetLike) -> None:
        # Flatten list and resolve SourceLike objects to find all Nodes
        to_process: List[FileSetLike] = [sources]
        while to_process:
            processing = to_process.pop()
            if hasattr(processing, "target"):
                to_process.append(processing.target)
            elif isinstance(processing, Node):
                self.depends.add(processing)
                self._sources.append(processing)
            elif isinstance(processing, (str, Path)):
                # For convenience, string literals and paths are allowed here but only if they
                # can be resolved to a File or a Dir immediately. Otherwise, it's ambiguous.
                path = self.env.root.joinpath(processing)
                try:
                    entry = self.env.execution.entries[path]
                except KeyError as e:
                    if path.is_file():
                        entry = self.env.file(path)
                    elif path.is_dir():
                        entry = self.env.dir(path)
                    else:
                        raise ValueError(
                            f"Path {processing} not found. If this path will be generated, "
                            f"declare it either a file or directory with env.file() or "
                            f"env.dir()"
                        ) from e
                self.depends.add(entry)
                self._sources.append(entry)
            elif isinstance(processing, Iterable):
                to_process.extend(processing)
            else:
                raise TypeError(f"Unknown source type {processing!r}")

    def __iter__(self) -> Iterator[File]:
        # Deduplicate files from all our sources. It's possible that a file may be
        # included more than once if, for example, we include a directory and also
        # explicitly some files within the directory.
        seen: Set[File] = set()
        for item in self._sources:
            if item in seen:
                continue
            elif isinstance(item, File):
                seen.add(item)
                yield item
            elif isinstance(item, (Dir, FileSet)):
                for subitem in item:
                    if subitem not in seen:
                        seen.add(subitem)
                        yield subitem
