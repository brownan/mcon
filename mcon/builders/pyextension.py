from __future__ import annotations

import os.path
import shlex
import subprocess
import sys
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Collection, Optional, Sequence, Tuple

from mcon import Environment, File, FileLike
from mcon.builder import Builder
from mcon.builders.c import CompiledObject, CompilerConfig, SharedLibrary


@lru_cache
def get_compiler_params() -> Tuple[CompilerConfig, str]:
    # Get compiler and compiler options we need to build a python extension module
    (
        cc,
        cxx,
        cflags,
        ccshared,
        ldshared,
        ext_suffix,
    ) = sysconfig.get_config_vars(
        "CC",
        "CXX",
        "CFLAGS",
        "CCSHARED",
        "LDSHARED",
        "EXT_SUFFIX",
    )

    paths = sysconfig.get_paths()

    include_dirs = {
        paths["include"],
        paths["platinclude"],
    }

    # Include Virtualenv
    if sys.exec_prefix != sys.base_exec_prefix:
        include_dirs.add(os.path.join(sys.exec_prefix, "include"))

    # Platform library directories
    library_dirs = {
        paths["stdlib"],
        paths["platstdlib"],
    }

    ldparts = shlex.split(ldshared)
    ld = ldparts[0]
    ldflags = ldparts[1:]

    return (
        CompilerConfig(
            cc=cc,
            cxx=cxx,
            cflags=shlex.split(ccshared) + shlex.split(cflags),
            ld=ld,
            ldflags=ldflags,
            include_dirs=include_dirs,
            lib_dirs=library_dirs,
        ),
        ext_suffix,
    )


def find_full_module_name(source: Path, namespace_packages: Collection[Path] = ()) -> str:
    """Given the path to a module, returns the fully qualified module name

    Because namespace packages can't be detected programmatically, they must be given explicitly
    """
    parts = [source.stem]
    dir = source.parent
    while True:
        has_init = any(
            dir.joinpath(init).exists()
            for init in [
                "__init__.py",
                "__init__.pyc",
                "__init__.pyx",
                "__init__.pxd",
            ]
        )
        is_namespace = dir in namespace_packages

        if not has_init and not is_namespace:
            break

        parts.append(dir.name)
        dir = dir.parent

    return ".".join(reversed(parts))


class ExtensionModule:
    def __init__(
        self,
        env: Environment,
        source: FileLike,
        extra_sources: Optional[Sequence[FileLike]] = None,
    ):
        module = env.file(source)
        conf, ext_suffix = get_compiler_params()

        # Name the build directories similar to how setuptools names them
        platform_specifier = f"{sysconfig.get_platform()}-{sys.implementation.cache_tag}"
        build_dir: Path = env.build_root / f"temp.{platform_specifier}"
        lib_dir: Path = env.build_root / f"lib.{platform_specifier}"

        sources = [module]
        if extra_sources:
            sources.extend(env.file(s) for s in extra_sources)

        self.objects = [
            CompiledObject(env, s.derive(build_dir, ".o"), s, conf) for s in sources
        ]
        self.target = env.file(
            SharedLibrary(
                env,
                module.derive(lib_dir, ext_suffix),
                self.objects,
                conf,
            )
        )


class CythonModule(Builder):
    def __init__(self, env: Environment, source: FileLike, full_module_name: str):
        super().__init__(env)
        self.source: File = self.depends_file(source)
        self.c_file = self.register_target(self.source.derive("cython", ".c"))
        self.full_module_name = full_module_name

        ext_mod = ExtensionModule(
            env,
            self.c_file,
        )
        self.target = env.file(ext_mod)

        # Export the object files as an attribute so that callers can target just those files
        self.objects = ext_mod.objects

    def __str__(self) -> str:
        return f"Cythonizing {self.source} ({self.full_module_name})"

    def build(self) -> None:
        # Launch cython via a small python script in a subprocess. This is pretty much what
        # cython's stock command line interface would call, except here we can specify the
        # full module name.
        # This is important because the current version of cython doesn't detect the
        # full module name within namespace packages and can't be specified on the
        # command line.
        # We can't invoke this function directly because cython isn't thread safe.
        # We could in theory launch using multiprocessing or a concurrent.futures process pool
        # with one worker, but we'd have to use a multiprocessing "spawn" context, not "fork",
        # because it may be launched from a non-main thread. I chose this approach even though
        # it's a bit more of a hack just because multiprocessing brings with it a huge amount
        # of extra complexity with its IPC when all we really need is to call a single function.

        launch_prog = (
            "import sys;"
            "from Cython.Compiler.Main import compile_single as c;"
            "from Cython.Compiler.CmdLine import parse_command_line as p;"
            "o,s=p(sys.argv[1:]);"
            "c(s[0],o,{!r})".format(self.full_module_name)
        )
        cmdline = [
            sys.executable,
            "-c",
            launch_prog,
            "-3",
            "-o",
            str(self.c_file.path),
            str(self.source.path),
        ]
        subprocess.check_call(cmdline)
