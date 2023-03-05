import subprocess

from mcon import Builder, DirLike, Environment


class Sphinx(Builder):
    """Sphinx documentation builder"""

    def __init__(self, env: Environment, target: DirLike, source: DirLike):
        super().__init__(env)
        self.target = self.register_target(env.dir(target))
        self.source = self.depends_dir(source)

    def build(self) -> None:
        subprocess.check_call(
            [
                "sphinx-build",
                self.source.path,
                self.target.path,
            ]
        )
