from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Collection,
    Dict,
    Iterable,
    Iterator,
    List,
    MutableSet,
    Optional,
    Type,
    Union,
)

if TYPE_CHECKING:
    from minicons.builder import Builder
    from minicons.environment import Environment
    from minicons.types import E


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


class Entry(Node, ABC):
    """Represents a file or a directory on the filesystem with a path

    The path may or may not exist until it is built. After its builder builds it,
    the path is expected to exist.
    """

    def __new__(cls: Type[E], env: Environment, path: Union[Path, str]) -> E:
        # Make sure path is always absolute, interpreting relative paths as relative
        # to the environment root
        path = env.root.joinpath(path)

        # See if this entry already exists
        try:
            entry = env.execution.entries[path]
            if not isinstance(entry, cls):
                raise TypeError(f"Path {path} already exists but is the wrong type")
            return entry
        except KeyError:
            pass

        entry = super().__new__(cls)
        return entry

    def __init__(
        self,
        env: "Environment",
        path: Union[Path, str],
    ):
        super().__init__(env)
        self.path: Path = env.root.joinpath(path)

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

    def derive(self: "E", build_dir_name: str, new_ext: Optional[str] = None) -> "E":
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
        self.path.unlink(missing_ok=True)


class Dir(Entry, Collection[File]):
    """A directory of files

    The directory referred to by the Dir object may not exist until it is built.
    After building, the Dir object may be treated as a Collection of File objects, or
    treated as a single unit (moved around, passed to another builder that expects a Dir,
    etc)
    """

    def __init__(self, env: "Environment", path: Union[Path, str], glob: str = "**/*"):
        super().__init__(env, path)
        self.glob_pattern = glob

    def __iter__(self) -> Iterator["File"]:
        for path in self.path.glob(self.glob_pattern):
            if path.is_file():
                yield self.env.file(path)

    def __contains__(self, item: Any) -> bool:
        return any(item == d for d in self)

    def __len__(self) -> int:
        return sum(1 for _ in self)

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
        if self.path.is_dir():
            shutil.rmtree(self.path)


class FileSet(Node, Iterable[File]):
    """A set of files whose contents is not necessarily known until build time after
    the fileset has been built.

    A builder that outputs a FileSet is expected to add files to it during the build phase.
    The downstream builders which depend on this FileSet will then have access to the
    final set of files within the FileSet.

    Note: If a builder is, during the build phase, creating File and/or Dir objects in
    arbitrary locations with intent to add them to a target FileSet, the parent
    directories of those files are not automatically created (unlike with File and Dir
    targets, where .prepare() is called to create the parent directories before
    Builder.build() is called)

    """

    def __init__(self, env: Environment):
        super().__init__(env)
        self._sources: List[Node] = []

    def add(self, item: Node) -> None:
        self._sources.append(item)
        self.depends.add(item)

    def __iter__(self) -> Iterator[File]:
        for item in self._sources:
            if isinstance(item, File):
                yield item
            elif isinstance(item, (Dir, FileSet)):
                yield from iter(item)