from minicons import Environment, register_alias
from minicons.builders.python import Wheel

env = Environment()
wheel = Wheel(env, tag="py38-none-any")

wheel.add_wheel_sources(
    [
        env.root.glob("minicons/**/*.py"),
    ]
)
wheel.add_sdist_sources(
    ["construct.py", "pyproject.toml", env.root.glob("minicons/**/*.py")]
)

register_alias("wheel", wheel.wheel)
register_alias("sdist", wheel.sdist)
