import shutil

from mcon import DirLike, Environment, FileLike, FileSet, FileSetLike, StrPath
from mcon.builder import Builder, SingleFileBuilder


class Install(SingleFileBuilder):
    """Copy a single file from source ta target"""

    def __init__(self, env: Environment, target: FileLike, source: FileLike):
        super().__init__(env, target)
        self.source = self.depends_file(source)

    def build(self) -> None:
        shutil.copy2(self.source.path, self.target.path)

    def __str__(self) -> str:
        return f"Installing {self.target}"


class InstallFiles(Builder):
    """Installs multiple files into a common destination directory, preserving directory
    structures of the source files relative to a given root.

    All files must be within the given root.

    Note: This builder may need to re-copy its files even if the source files haven't
    changed. This is because the builder cannot generally know what set of files it
    needs to copy -- a source FileSet may itself have changed, and so InstallFiles
    has no way to know this until build time.

    Therefore, if a dependent builder uses an InstallFiles builder as a source, and that
    dependent builder needs to be built for some other reason, this InstallFiles builder
    must necessarily run.

    (additional optimizations could be made by introspecting the sources to see
    if there are any other FileSets within, and in that case generating the target
    fileset statically. But I wanted to avoid adding all sorts of exceptions and fast
    code paths to the software at this stage, focusing instead on correctness)

    """

    def __init__(
        self,
        env: Environment,
        destdir: DirLike,
        sources: FileSetLike,
        *,
        relative_to: StrPath = ".",
    ) -> None:
        super().__init__(env)
        self.destdir = env.dir(destdir)
        self.target: FileSet = self.register_target(FileSet(env))
        self.sources: FileSet = self.depends_files(sources)
        self.relative_to = self.env.root.joinpath(relative_to)

    def __str__(self) -> str:
        return "InstallFiles({})".format(self.destdir.path)

    def build(self) -> None:
        for file in self.sources:
            rel_path = file.relative_to(self.relative_to)
            final_path = self.destdir.path / rel_path
            final_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file.path, final_path)
            self.target.add(self.env.file(final_path))
