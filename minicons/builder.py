from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, Iterable, List, Union

from minicons.entry import Dir, Entry, File
from minicons.types import BuilderType, DirSource, FileSet, FileSource, FilesSource

if TYPE_CHECKING:
    from minicons.environment import Environment


class Builder(ABC, Generic[BuilderType]):
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

    def __init__(self, env: "Environment", target: BuilderType):
        self.env = env

        # Which other entries this builder depends on
        # These dependencies are resolved at build time. Conceptually this translates to
        # all of this builder's output (target) entries depend on each entry in this list.
        self.depends: List["Entry"] = []

        # List of items this builder builds. It is populated by the target(s) passed in,
        # but may be added to by calling side_effects()
        self.builds: List["Entry"] = []

        # Register the target(s) as being built by this builder
        self.target: BuilderType = target
        if isinstance(target, (File, Dir)):
            self.builds.append(target)
            target.builder = self
        elif isinstance(target, Iterable):
            file: File
            for file in target:
                if not isinstance(file, File):
                    raise ValueError(
                        "Builder target passed a non-File in with the FileSet"
                    )
                file.builder = self
                self.builds.append(file)
        elif isinstance(target, str):
            raise TypeError(
                "Cannot pass a string in as a target. Use env.file() on env.dir() to explicitly "
                "pass a File or Directory object"
            )
        else:
            raise TypeError(f"Invalid target object {target!r}")

    def __str__(self) -> str:
        return "{}({})".format(type(self).__name__, " ".join(str(b) for b in self.builds))

    def side_effect(self, entries: Union["Entry", Iterable["Entry"]]) -> None:
        """Registers additional entries as outputs of the current builder, in addition
        to the files the builder returned from get_targets()

        Builders should call this to declare additional files they output.

        """
        if isinstance(entries, Entry):
            entries = [entries]
        for entry in entries:
            if entry.builder and entry.builder is not self:
                raise ValueError(f"{entry} is already being built by {entry.builder}")
            entry.builder = self
            self.builds.append(entry)

    @abstractmethod
    def build(self) -> None:
        """Called to actually build the targets

        The builder is expected to write to the filesystem the target file(s) in self.target,
        as well as any declared side effect files.
        """

    # Shorthand convenience methods on the builder
    def depends_file(self, source: FileSource) -> "File":
        return self.env.depends_file(self, source)

    def depends_files(self, sources: FilesSource) -> FileSet:
        return self.env.depends_files(self, sources)

    def depends_dir(self, source: DirSource) -> "Dir":
        return self.env.depends_dir(self, source)
