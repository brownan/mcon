from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Generic, List, Optional, TypeVar

from mcon.entry import Dir, File, FileSet, Node
from mcon.types import DirLike, FileLike, FileSetLike, SourceType

if TYPE_CHECKING:
    from mcon.environment import Environment

N = TypeVar("N", bound=Node)


class Builder(ABC):
    """Base builder class. Builder classes define how to build one or more files.

    During construction, builders have two responsibilities: set up their targets and
    their dependencies.

    Builders declare their targets (files they build) by calling their .register_target()
    method. Declaring targets is how the framework knows to call this builder when a
    target needs rebuilding.

    Builders must declare the files they depend on by using one of these methods provided
    by the Environment:
    self.depends_file()
    self.depends_files()
    self.depends_dir()

    These three methods return a File, FileSet, and Dir object respectively. Their parameter
    is one of several objects that may be coerced to the respective output type, such as a string,
    Path object, File object, list of the above, Dir object, or any SourceLike object (has
    a .target attribute with the appropriate type. This can be the builder object itself
    if it implements that interface)

    It is critical that Builders use the depends_*() methods to declare their dependencies,
    and use register_target() to declare their outputs, so that dependency tracking works
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

        The builder is expected to write to the filesystem the target file(s) it has
        previously declared.
        """
        raise NotImplementedError

    def register_target(self, node: N) -> N:
        """Registers entries as outputs of the current builder

        Builders should call this for each file it will create during the build phase.
        If the framework determines a file needs (re)building, it will call this builder
        to do so.

        """
        if node.builder and node.builder is not self:
            raise ValueError(f"{node} is already being built by {node.builder}")
        node.builder = self
        self.builds.append(node)
        return node

    def depends_file(self, source: FileLike) -> File:
        """Resolves and registers the given file as a dependency of this builder"""
        file = self.env.file(source)
        self.depends.append(file)
        return file

    def depends_files(self, sources: FileSetLike) -> FileSet:
        """Resolves and registers the given files and directories as dependencies of this
        builder, returning a new FileSet


        """
        fileset = FileSet(self.env)
        self.depends.append(fileset)
        fileset.add(sources)
        return fileset

    def depends_dir(self, source: DirLike) -> "Dir":
        """Resolves and registers the given directory as a dependency of this builder"""
        d = self.env.dir(source)
        self.depends.append(d)
        return d


# Below are some convenience subclasses for common builder patterns
class SingleFileBuilder(Builder, ABC):
    """A builder that outputs a single file

    This sets up and registers a target given by the caller. Usual convention is to have
    the caller tell a builder where to output its file. Thus, the target is passed in as
    a parameter and then registered as a target.
    """

    def __init__(self, env: Environment, target: FileLike):
        super().__init__(env)
        self.target: File = self.register_target(env.file(target))

    def __str__(self) -> str:
        return f"Building {self.target}"


class Command(Builder, Generic[SourceType]):
    """Runs the given python function to generate a file, dir, or fileset

    This is a quick way to create a one-off builder that builds something

    The given target can be a File, Dir, or FileSet.

    The given command is a callable function which is run to build the target. It is
    passed as a parameter the target File, but not the sources -- it is expected to use another
    mechanism such as a closure to read from its sources.

    The sources parameter is a convenience for registering the files and directories that
    must be built before this builder runs.

    """

    def __init__(
        self,
        env: Environment,
        target: SourceType,
        sources: Optional[FileSetLike],
        command: Callable[[SourceType], Any],
        str_func: Optional[Callable[[SourceType], str]] = None,
    ):
        super().__init__(env)
        self.target: SourceType = self.register_target(target)
        self.command = command
        self.str_func = str_func
        if sources is not None:
            self.depends_files(sources)

    def __str__(self) -> str:
        if self.str_func:
            return self.str_func(self.target)
        else:
            return f"Building {self.target}"

    def build(self) -> None:
        self.command(self.target)
