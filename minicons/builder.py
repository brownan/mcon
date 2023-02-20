from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Union

from minicons.entry import Dir, Entry, File
from minicons.types import DirSource, E, FileSet, FileSource, FilesSource, SourceLike

if TYPE_CHECKING:
    from minicons.environment import Environment


class Builder(ABC):
    """Base builder class. Builder classes define how to build one or more files.

    All derived files must have a declared builder. Builders come in three types, shown
    along with their respective type signature declarations:
    1) Outputs a single file
       class MyBuilder(Builder[File]): ...
    2) Outputs multiple files
       class MyBuilder(Builder[FileSet]): ...
    3) Outputs a directory
       class MyBuilder(Builder[Dir]): ...

    (If you're not using type checking, you can omit the generic part of the type signature)

    Builders declare the files they build by returning a File, FileSet, or Dir object
    from their .get_targets() method. Subclasses must override and implement get_targets().

    Builders must declare the files they depend on by using one of these methods provided
    by the Environment:
    self.env.depends_file()
    self.env.depends_files()
    self.env.depends_dir()

    These three methods return a File, FileSet, and Dir object respectively. Their parameter
    is one of several objects that may be coerced to the respective output type, such as a string,
    Path object, File object, list of the above, Dir object, or another Builder.

    If a Builder is passed to one of those methods, that builder must return the matching
    type as its target.

    Builders may have other files it generates as a side effect other than the ones returned
    by .get_targets(). These are declared by passing them to self.side_effect(). Those files
    may be made available as the builder sees fit (for example, as an attribute or by passing
    to another internally wrapped builder instance).

    It is critical that Builders use the env.depends_*() methods to declare their dependencies,
    and use either get_targets() or side_effects() to declare their outputs, so that dependency
    tracking to work correctly.
    """

    def __init__(self, env: "Environment"):
        self.env = env

        # Which other entries this builder depends on
        # These dependencies are resolved at build time. Conceptually this translates to
        # all of this builder's output (target) entries depend on each entry in this list.
        self.depends: List["Entry"] = []

        # List of items this builder builds.
        self.builds: List["Entry"] = []

    def __str__(self) -> str:
        return "{}({})".format(type(self).__name__, " ".join(str(b) for b in self.builds))

    @abstractmethod
    def build(self) -> None:
        """Called to actually build the targets

        The builder is expected to write to the filesystem the target file(s) in self.target,
        as well as any declared side effect files.
        """

    def register_target(self, entry: E) -> E:
        """Registers entries as outputs of the current builder

        Builders should call this to declare additional files they output.

        """
        if entry.builder and entry.builder is not self:
            raise ValueError(f"{entry} is already being built by {entry.builder}")
        entry.builder = self
        self.builds.append(entry)
        return entry

    def depends_file(self, source: FileSource) -> File:
        """Resolves and registers the given source as a dependency of this builder"""
        if isinstance(source, SourceLike):
            if not isinstance(source.target, File):
                raise ValueError(f"Wrong target type {source!r}")
            file = source.target
        else:
            file = self.env.file(source)
        self.depends.append(file)
        return file

    def depends_files(self, sources: FilesSource) -> FileSet:
        """Resolves and registers the given sources as dependencies of this builder

        Resolves the given sources and returns a Collection of File objects.
        This is typically either a list of files or a Dir, but returned objects
        are not guaranteed to be exactly those types.

        """
        if isinstance(sources, SourceLike):
            sources = sources.target

        if isinstance(sources, Dir):
            self.depends.append(sources)
            return sources
        elif isinstance(sources, File):
            self.depends.append(sources)
            return [sources]
        elif isinstance(sources, str):
            file = self.env.file(sources)
            self.depends.append(file)
            return [file]
        elif isinstance(sources, Iterable):
            files = [self.env.file(s) for s in sources]
            self.depends.extend(files)
            return files
        else:
            raise ValueError(f"Unknown source type {sources}")

    def depends_dir(self, source: DirSource) -> "Dir":
        """Resolves and registers the given Dir as a dependency of this builder"""
        if isinstance(source, SourceLike):
            source = source.target
        self.depends.append(source)
        return source


# Below are some convenience subclasses for common builder patterns
class SingleFileBuilder(Builder):
    def __init__(self, env: Environment, target: Union[File, Path, str]):
        super().__init__(env)
        self.target: File
        if isinstance(target, (str, Path)):
            self.target = self.env.file(target)
        else:
            self.target = target
        self.register_target(self.target)


class MultipleFilesBuilder(Builder):
    def __init__(self, env: Environment, targets: Iterable[Union[File, Path, str]]):
        super().__init__(env)
        target_list: List[File] = []
        for target in targets:
            if isinstance(target, (str, Path)):
                target = self.env.file(target)
            target_list.append(target)
            self.register_target(target)
        self.target: FileSet = target_list


class DirBuilder(Builder):
    def __init__(self, env: Environment, target: Union[Dir, Path, str]):
        super().__init__(env)
        self.target: Dir
        if isinstance(target, (str, Path)):
            self.target = self.env.dir(target)
        else:
            self.target = target
        self.register_target(self.target)
