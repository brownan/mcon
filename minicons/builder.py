from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, List, Optional, TypeVar

from minicons.entry import Dir, File, FileSet, Node
from minicons.types import DirSource, FileArg, FileSource, FilesSource

if TYPE_CHECKING:
    from minicons.environment import Environment

N = TypeVar("N", bound=Node)


class Builder(ABC):
    """Base builder class. Builder classes define how to build one or more files.

    Builders declare the files they build by calling their .register_target() method.
    Declaring targets is how the framework knows to call this builder when the given
    target needs rebuilding.

    Builders must declare the files they depend on by using one of these methods provided
    by the Environment:
    self.env.depends_file()
    self.env.depends_files()
    self.env.depends_dir()

    These three methods return a File, FileSet, and Dir object respectively. Their parameter
    is one of several objects that may be coerced to the respective output type, such as a string,
    Path object, File object, list of the above, Dir object, or any SourceLike object (has
    a .target attribute with the appropriate type. This can be the builder object itself
    if it implements that interface)

    It is critical that Builders use the env.depends_*() methods to declare their dependencies,
    and use .register_target() to declare their outputs, so that dependency tracking works
    correctly.
    """

    def __init__(self, env: Environment):
        self.env = env

        # Which other entries this builder depends on
        # These dependencies are resolved at build time. Conceptually this translates to
        # all of this builder's output (target) entries depend on each entry in this list.
        self.depends: List[Node] = []

        # List of items this builder builds.
        self.builds: List[Node] = []

    def __str__(self) -> str:
        return "{}({})".format(type(self).__name__, " ".join(str(b) for b in self.builds))

    @abstractmethod
    def build(self) -> None:
        """Called to actually build the targets

        The builder is expected to write to the filesystem the target file(s) in self.target,
        as well as any declared side effect files.
        """
        raise NotImplementedError

    def register_target(self, node: N) -> N:
        """Registers entries as outputs of the current builder

        Builders should call this to declare additional files they output.

        """
        if node.builder and node.builder is not self:
            raise ValueError(f"{node} is already being built by {node.builder}")
        node.builder = self
        self.builds.append(node)

        # If this is a fileset with a pre-populated set of files (not files dynamically
        # generated) then also register them with this builder.
        # This makes it easy for the builder pattern where they generate a lot of
        # known files, add them to a fileset, then register them as a single unit.
        # Maybe this is a shortcut instead of a builder registering files individually
        # and setting its .target attribute to a list, or maybe the builder plans to add
        # more files to the fileset during the build phase.
        # In either case, we have to set these files' builder so that the execution process
        # doesn't complain about certain files not existing at the start of the build.
        if isinstance(node, FileSet):
            for sub_file in node:
                self.register_target(sub_file)

        return node

    def depends_file(self, source: FileSource) -> File:
        """Resolves and registers the given source as a dependency of this builder"""
        if hasattr(source, "target"):
            if not isinstance(source.target, File):
                raise TypeError(f"Wrong target type {source!r}")
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
        fileset = FileSet(self.env)
        self.depends.append(fileset)
        fileset.add(sources)
        return fileset

    def depends_dir(self, source: DirSource) -> "Dir":
        """Resolves and registers the given Dir as a dependency of this builder"""
        if hasattr(source, "target"):
            if not isinstance(source.target, Dir):
                raise TypeError(f"Wrong target type: {source!r}")
            d = source.target
        else:
            d = self.env.dir(source)
        self.depends.append(d)
        return d


# Below are some convenience subclasses for common builder patterns
class SingleFileBuilder(Builder, ABC):
    def __init__(self, env: Environment, target: FileArg):
        super().__init__(env)
        self.target: File = self.register_target(env.file(target))

    def __str__(self) -> str:
        return f"Building {self.target}"


class Command(SingleFileBuilder):
    """Runs the given python function to generate a file"""

    def __init__(
        self,
        env: Environment,
        target: FileArg,
        command: Callable[[File], Any],
        str_func: Optional[Callable[[File], str]] = None,
    ):
        super().__init__(env, target)
        self.command = command
        self.str_func = str_func

    def __str__(self) -> str:
        if self.str_func:
            return self.str_func(self.target)
        else:
            return f"Building {self.target}"

    def build(self) -> None:
        self.command(self.target)
