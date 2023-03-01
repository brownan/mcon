from minicons import Environment, register_alias
from minicons.builders.python import Distribution

env = Environment()
dist = Distribution(env)

wheel = dist.wheel("py38-none-any")
wheel.add_sources(
    [
        env.root.glob("minicons/**/*.py"),
        "minicons/py.typed",
    ]
)
register_alias("wheel", wheel)

sdist = dist.sdist()
sdist.add_sources(
    [
        "construct.py",
        "pyproject.toml",
        env.root.glob("minicons/**/*.py"),
        env.root.glob("tests/**/*.py"),
        "minicons/py.typed",
        ".pre-commit-config.yaml",
        ".gitignore",
    ]
)
register_alias("sdist", sdist)
