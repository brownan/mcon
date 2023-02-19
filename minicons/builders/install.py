import shutil

from minicons import Builder, Environment, File


class Install(Builder[File]):
    def __init__(self, env: Environment, target: File, source: File):
        super().__init__(env, target)
        self.source = self.depends_file(source)

    def build(self) -> None:
        shutil.copy2(self.source.path, self.target.path)
