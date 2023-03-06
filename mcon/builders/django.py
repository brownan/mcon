import shutil
import subprocess

from mcon import Builder, DirLike, Environment


class CollectStatic(Builder):
    """Calls into Django's collect static routine"""

    def __init__(self, env: Environment, target: DirLike):
        super().__init__(env)
        self.target = self.register_target(env.dir(target))

    def build(self) -> None:
        manage_py = self.env.root / "manage.py"
        static_output_dir = subprocess.check_output(
            [
                str(manage_py),
                "shell",
                "-c",
                "from django.conf import settings; import sys; sys.stdout.buffer.write("
                "settings.STATIC_ROOT.encode('utf-8'))",
            ],
            encoding="utf-8",
        )
        subprocess.check_call(
            [
                str(self.env.root / "manage.py"),
                "collectstatic",
                "--no-input",
            ]
        )
        shutil.copytree(static_output_dir, self.target.path)
