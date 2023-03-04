import os.path
import shlex
import subprocess
import sys
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence, Tuple

from mcon import Environment, File, FileLike
from mcon.builder import Command
from mcon.builders.c import CompiledObject, CompilerConfig, SharedLibrary


@lru_cache
def get_compiler_params() -> Tuple[CompilerConfig, str]:
    # Get compiler and compiler options we need to build a python extension module
    (cc, cxx, cflags, ccshared, ldshared, ext_suffix,) = sysconfig.get_config_vars(
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

        objects = [
            CompiledObject(env, s.derive(build_dir, ".o"), s, conf) for s in sources
        ]
        self.target = SharedLibrary(
            env,
            module.derive(lib_dir, ext_suffix),
            objects,
            conf,
        )


class CythonModule:
    def __init__(self, env: Environment, source: FileLike):
        module: File = env.file(source)
        c_file = Command(
            env,
            module.derive("cython", ".c"),
            module,
            lambda file: subprocess.check_call(
                [
                    "cython",
                    "-3",
                    "-o",
                    str(file.path),
                    str(module.path),
                ]
            ),
            (lambda file: f"Cythonizing {file}"),
        )

        self.target = ExtensionModule(
            env,
            c_file,
        )
