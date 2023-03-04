# MCon

Mini software construction and build framework

## About MCon

MCon provides a framework for building software similar to Make or SCons. Dependencies and build
definitions are declared via a Python script, and the framework computes a dependency graph,
determines what needs building, and executes the defined builders.

MCon's initial purpose was to have a small tool to build Python Wheel distribution files while
still being flexible enough to integrate in other build steps such as extension modules, Cython
translation, Sphinx documentation building, Django collect static steps, etc. However, MCon's
core framework is flexible enough to build software other than Python distributions.

## Project Goals

* Use Python scripts to specify build dependencies and build processes.
* Statically compute a dependency graph and a "to build" list before any building starts
* Fully type annotated to enable strong typing in construction files.
* Support Builders with dynamic sets of output files
* Flexible Builder API

MCon is heavily influenced by, and shares many similarities with SCons. But the goals for mcon
are slightly different. SCons forces a common interface for builders, which enables
better composeability of builders within a larger dependency graph. However, in my opinion it
makes extending and writing your own builders more cumbersome. Writing your own builder is not
a top priority in SCons (for example, extending SCons isn't covered in the manual until chapter
17), and instead SCons relies on its extensive standard library of built-in builders.

With mcon, a Builder is just a class with a ``build()`` method. Builders declare targets and
declare dependencies, but otherwise are free to expose whatever API they wish to the rest of
your construction code.

Strong typing and full mypy compatibility make up for this loosely defined builder interface.
Builders will, by convention, provide a ``.target`` attribute to expose to other builders the
file(s) they build, but this is not required. The Python distribution builder, for example,
provides a ``.wheel()`` and ``.sdist()`` *method* to expose those respective targets for use as
a source in other builders.

MCon is written from scratch to be extensible and embeddable into a larger project, in addition
to providing a command line interface. As an example, the ``pybuild.py`` module provides a
PEP 517 build backend for integrating with build frontend tools such as pip and
[build](https://pypa-build.readthedocs.io/en/stable/index.html).

## Installing mcon

Install mcon with ``pip install mcon``

If developing mcon itself, check out the source code from https://github.com/brownan/mcon and then
install in editable mode with ``pip install -e '.[dev]'``

## MCon quickstart

Create a ``construct.py`` file in the top level directory of your project.

This script is run to declare a number of "builders" which define how to build various files.

Each script should create an ``mcon.Environment`` object with with everything else is associated.

After that, create a number of builder objects for each item you want to build. Here's an example
of a simple construct.py to build a C program:

```python
from mcon import Environment, register_alias
from mcon.builders.c import Program

env = Environment()
program = Program(env, "hello", "hello.c")
register_alias("all", program)
```

Now running ``mcon all`` on the command line will build the program ``hello`` from the source
file ``hello.c``

A few stock builders are provided, but I have only written and included so far the builders that
I personally need and use. The builder interface is relatively easy to use, so I encourage
you to write your own Builders for your own purposes rather than relying on a large library of
stock builders.

Yes, this makes the framework a bit less platform independent, and hopefully one day we'll get
a more extensive and platform-independent set of generic builders. But since that's a lot of work,
the idea for now is to make writing new builders as easy as possible for developers.

## Building Python Distributions

Included is a Python Distribution builder. This build system does not rely on setuptools and
is written from scratch to produce valid wheel files and compile valid Python extension modules.

To use this builder, create a Distribution object in your construct file, and then call
``.wheel()`` to generate a wheel target. The returned ``Wheel`` object has a ``.add_sources()``
method which should be called with the complete set of source files to add to the wheel.

Similarly, use ``Wheel.sdist()`` to create a source distribution target. The returned object also
has a ``.add_sources()`` method, which should get the set of files to include in the source
distribution.

Here's a simple example:
```python
from mcon import Environment, register_alias
from mcon.builders.python import Distribution, get_pure_tag

env = Environment()
dist = Distribution(env)

wheel_sources = [
    env.root.glob("mcon/**/*.py"),
    "mcon/py.typed",
]

wheel = dist.wheel(get_pure_tag())
wheel.add_sources(wheel_sources)
register_alias("wheel", wheel)

sdist = dist.sdist()
sdist.add_sources(wheel_sources + ["pyproject.toml", "construct.py", "README.md"])
sdist.add_sources(env.root.glob("test/**/*.py"))
register_alias("sdist", sdist)
```

Running ``mcon wheel sdist`` will now build both a wheel file and source distribution and place
them in the `dist` directory (by default).

## Project Status

I'd consider this project to be in the "alpha" stage, in that I think it's in a state that may
be useful to others, but the ideas and interfaces are not necessarily finalized. As I use mcon
for my own other projects, I'll be refining and improving it.
