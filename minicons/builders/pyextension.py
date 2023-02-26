import os.path
import shlex
import sys
import sysconfig
from pathlib import Path

from minicons import Builder, Environment, File, FileSet, FileSource, FilesSource
from minicons.builders.c import CompilerConfig


def get_compiler_params():
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


class ExtensionModule(Builder[File]):
    def __init__(self, env: Environment, module: FileSource, extra_sources: FilesSource):
        self.module = self.depends_file(module)
        self.extra_sources = self.depends_files(extra_sources)
        self.conf, ext_suffix = get_compiler_params()

        platform_specifier = f"{sysconfig.get_platform()}-{sys.implementation.cache_tag}"
        self.build_dir: Path = self.env.build_root / f"temp.{platform_specifier}"
        self.lib_dir: Path = self.env.build_root / f"lib.{platform_specifier}"

        super().__init__(env, self.module.derive("lib", ext_suffix))

    def install_inplace(self) -> FileSet:
        pass

    def build(self) -> None:
        pass
