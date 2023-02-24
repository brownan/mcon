from pathlib import Path
from typing import Optional, Union

from minicons.entry import Dir, File
from minicons.execution import Execution, get_current_execution


class Environment:
    """An Environment object controls the context in which Builders live

    An Environment exists to define the root directory and build directory for Builders
    attached to that environment. File and Dir objects created within the environment
    will resolve their paths relative to the environment's root.

    Multiple Environments can exist within a single Execution, meaning Builders will use
    the root and build directories attached to their respective environments.

    The build directory is intended to be the directory where derived, intermediate files
    are saved by Builder implementations. Builders should use Environment.get_build_path()
    or Entry.derive() to automatically choose a suitable place for a derived file.

    If an Environment isn't initialized with an explicit Execution instance, the global
    Execution will be used (if one exists, otherwise an error is raised)
    """

    def __init__(
        self,
        *,
        root: Optional[Path] = None,
        build_root: Optional[Path] = None,
        execution: Optional[Execution] = None,
    ):
        if not execution:
            execution = get_current_execution()

        self.execution: Execution = execution
        self.root = root or self.execution.root
        self.build_root = build_root or self.root.joinpath("build")

    def file(
        self,
        path: Union[str, Path, "File"],
    ) -> "File":
        if isinstance(path, File):
            return path
        return File(self, path)

    def dir(
        self,
        path: Union[str, Path, "Dir"],
    ) -> "Dir":
        if isinstance(path, Dir):
            return path
        return Dir(self, path)

    def get_rel_path(self, src: Union[str, Path]) -> str:
        """Returns the path to the given source file relative to either the environment's
        root or the file's build directory

        If the given source is underneath an immediate subdirectory of the self.build_root
        directory, then the returned path is relative to that build subdirectory. Otherwise,
        the returned path is relative to self.root.

        >>> env = Environment()
        >>> env.get_rel_path("foo/bar/baz.txt")
            "foo/bar/baz.py"
        >>> env.get_rel_path("build/bdir/foo/bar/baz.txt")
            "foo/bar/baz.txt

        This is useful for discovering the original path to a file which may or may not be
        currently under a build directory. This allows better composibility of Builders.
        When a builder wishes to create a new file derived from some exsiting file, that
        Builder shouldn't care whether the file is an original source or itself derived
        and build in another build directory. Using get_rel_path() helps builders preserve
        the original relative directory regardless of whether the file is an "original"
        file or a derived file in a build directory.

        For builders where it's not important to preserve the original directory structure
        of files they build, use of this method is not necessary.
        """
        src = self.root.joinpath(src)

        # See if the build directory is one of the parents:
        try:
            index = src.parents.index(self.build_root)
        except ValueError:
            # Result is relative to the root
            rel_path = src.relative_to(self.root)
        else:
            # Result is relative to the directory under the build root
            rel_path = src.relative_to(src.parents[index - 1])

        return str(rel_path)

    def get_build_path(
        self,
        src: Union[str, Path],
        build_dir: Union[str, Path],
        new_ext: Optional[str] = None,
    ) -> Path:
        """Create a suitable path under self.build_root for files derived from src

        For a given "src" path, computes the same path but rooted at the given build directory.
        build_dir can be either a string, which is taken as the name of a subdirectory
        under self.build_root. build_dir can also be a Path, in which case it MUST refer
        to a direct subdirectory of self.build_root.

        This method should be used by any builders which need to output derived files from
        some source. Using this method ensures that the relative path structure is preserved
        regardless of whether the source is in the source tree or itself some derived file
        under a build directory.

        This builds on top of get_rel_path(). See get_rel_path() docstring for rationale on use
        of automatic path creation which preserves relative paths.


        >>> env = Environment()
        >>> env.get_build_path("src/foo/bar.c", "obj", ".o")
            "build/obj/src/foo/bar.o"
        >>> env.get_build_path("build/obj/src/foo/bar.o", "lib", ".so")
            "build/lib/src/foo/bar.so

        The new_ext parameter can be used to change the file extension. An empty string will
        strip the extension off entirely.
        """
        rel_path = self.get_rel_path(src)
        build_dir = self.build_root.joinpath(build_dir)

        full_path = build_dir.joinpath(rel_path)
        if new_ext is not None:
            full_path = full_path.with_suffix(new_ext)
        return full_path
