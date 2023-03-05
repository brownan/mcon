from mcon import Environment, register_alias
from mcon.builders.python import Distribution

env = Environment()
dist = Distribution(env)

wheel = dist.wheel("py38-none-any")
wheel.add_sources(
    [
        env.root.glob("mcon/**/*.py"),
        "mcon/py.typed",
    ]
)
register_alias("wheel", wheel)

sdist = dist.sdist()
sdist.add_sources(
    [
        "construct.py",
        "pyproject.toml",
        env.root.glob("mcon/**/*.py"),
        env.root.glob("tests/**/*.py"),
        "mcon/py.typed",
        ".pre-commit-config.yaml",
        ".gitignore",
        "README.md",
    ]
)
register_alias("sdist", sdist)

register_alias("editable", dist.editable("py38-none-any", "."))
