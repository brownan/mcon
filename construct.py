from minicons import Environment, register_alias
from minicons.builders.python import Distribution

env = Environment()
dist = Distribution(env)

wheel = dist.wheel("py38-none-any")
wheel.add_sources(env.root.glob("minicons/**/*.py"))
wheel.add_sources("tests/run_tests.py")
register_alias("wheel", wheel)

sdist = dist.sdist()
sdist.add_sources("construct.py")
sdist.add_sources("pyproject.toml")
sdist.add_sources(env.root.glob("minicons/**/*.py"))
register_alias("sdist", sdist)
