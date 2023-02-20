import shutil

from minicons import Environment, File
from minicons.builder import SingleFileBuilder


class Install(SingleFileBuilder):
    def __init__(self, env: Environment, target: File, source: File):
        super().__init__(env, target)
        self.source = self.depends_file(source)

    def build(self) -> None:
        shutil.copy2(self.source.path, self.target.path)
