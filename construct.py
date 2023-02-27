from minicons import Environment, register_alias
from minicons.builders.python import SDist, Wheel

env = Environment()
wheel = Wheel(env, tag="py38-none-any")

wheel.add_sources(
    [
        env.root.glob("minicons/**/*.py"),
    ]
)

sdist = SDist(env)
sdist.add_sources(["construct.py", "pyproject.toml", env.root.glob("minicons/**/*.py")])

register_alias("wheel", wheel)
register_alias("sdist", sdist)
