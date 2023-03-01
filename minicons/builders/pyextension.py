import os.path
import shlex
import subprocess
import sys
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from minicons import Builder, Environment, FileSource, FilesSource
from minicons.builder import Command
from minicons.builders.c import CompiledObject, CompilerConfig, SharedLibrary


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


class ExtensionModule(Builder):
    def __init__(
        self,
        env: Environment,
        module: FileSource,
        extra_sources: Optional[FilesSource] = None,
    ):
        super().__init__(env)
        self.module = self.depends_file(module)
        self.conf, ext_suffix = get_compiler_params()

        # Name the build directories similar to how setuptools names them
        platform_specifier = f"{sysconfig.get_platform()}-{sys.implementation.cache_tag}"
        self.build_dir: Path = self.env.build_root / f"temp.{platform_specifier}"
        self.lib_dir: Path = self.env.build_root / f"lib.{platform_specifier}"

        sources = [self.module]
        if extra_sources:
            sources += self.depends_files(extra_sources)

        objects = [
            CompiledObject(
                env, self.module.derive(self.build_dir, ".o"), sources, self.conf
            )
        ]
        self.target = self.depends_file(
            SharedLibrary(
                env,
                self.module.derive(self.lib_dir, ext_suffix),
                objects,
                self.conf,
            )
        )

    def build(self) -> None:
        pass


class CythonModule(Builder):
    def __init__(self, env: Environment, module: FileSource):
        super().__init__(env)
        self.module = self.depends_file(module)

        c_file = self.depends_file(
            Command(
                env,
                self.module.derive("cython", ".c"),
                lambda file: subprocess.check_call(
                    [
                        "cython",
                        "-3",
                        "-o",
                        str(file.path),
                        str(self.module.path),
                    ]
                ),
                (lambda file: f"Cythonizing {file}"),
            )
        )

        self.target = self.depends_file(
            ExtensionModule(
                env,
                c_file,
            )
        )

    def build(self) -> None:
        pass
