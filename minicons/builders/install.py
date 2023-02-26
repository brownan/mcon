import shutil
from pathlib import Path
from typing import Union

from minicons import Environment, File, FileSet, FilesSource
from minicons.builder import Builder, SingleFileBuilder


class Install(SingleFileBuilder):
    """Copy a single file from source ta target"""

    def __init__(self, env: Environment, target: File, source: File):
        super().__init__(env, target)
        self.source = self.depends_file(source)

    def build(self) -> None:
        shutil.copy2(self.source.path, self.target.path)


class InstallFiles(Builder):
    """Installs multiple files into a common destination directory, preserving directory
    structures of the source files relative to a given root.

    All files must be within the given root.

    """

    def __init__(
        self,
        env: Environment,
        destdir: Union[Path, str],
        sources: FilesSource,
        root: str = ".",
    ) -> None:
        super().__init__(env)
        self.destdir = Path(destdir)
        self.target: FileSet = self.register_target(FileSet(env))
        self.sources: FileSet = self.depends_files(sources)
        self.root = self.env.root.joinpath(root)

    def build(self) -> None:
        for file in self.sources:
            rel_path = file.relative_to(self.root)
            final_path = self.destdir / rel_path
            final_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file.path, final_path)
