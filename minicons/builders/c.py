import dataclasses
import shlex
import subprocess
from typing import Collection, Sequence

from minicons import Environment, File, FileLike, FileSetLike
from minicons.builder import SingleFileBuilder


@dataclasses.dataclass
class CompilerConfig:
    # C compiler
    cc: str = "cc"

    # C++ compiler
    cxx: str = "c++"

    # C compiler flags
    cflags: Sequence[str] = ()

    # CXX compiler flags
    cxxflags: Sequence[str] = ()

    # Flags common to both C and C++
    cppflags: Sequence[str] = ()

    # Object linker
    ld: str = "cc"

    # Linking flags
    ldflags: Sequence[str] = ()

    # Include directories
    include_dirs: Collection[str] = ()
    lib_dirs: Collection[str] = ()


class CompiledObject(SingleFileBuilder):
    def __init__(
        self,
        env: Environment,
        target: FileLike,
        sources: FileSetLike,
        compiler_config: CompilerConfig,
    ):
        super().__init__(env, target)
        self.sources = self.depends_files(sources)
        self.compiler_config = compiler_config

    def __str__(self) -> str:
        return f"Compiling {self.target}"

    def build(self) -> None:
        conf = self.compiler_config
        cmdline = shlex.split(conf.cc)
        cmdline += [
            "-c",
            "-o",
            str(self.target.path),
        ]
        cmdline += conf.cppflags
        cmdline += conf.cflags
        for incdir in conf.include_dirs:
            cmdline.extend(["-I", incdir])
        cmdline.extend(str(s.path) for s in self.sources)
        subprocess.check_call(cmdline)


class SharedLibrary(SingleFileBuilder):
    def __init__(
        self,
        env: Environment,
        target: File,
        sources: FileSetLike,
        compiler_config: CompilerConfig,
    ):
        super().__init__(env, target)
        self.sources = self.depends_files(sources)
        self.compiler_config = compiler_config

    def __str__(self) -> str:
        return f"Linking {self.target}"

    def get_targets(self) -> File:
        return self.target

    def build(self) -> None:
        conf = self.compiler_config
        cmdline = shlex.split(conf.cc)
        cmdline += [
            "-o",
            str(self.target.path),
        ]
        cmdline += conf.ldflags
        for libdir in conf.lib_dirs:
            cmdline.extend(["-L", libdir])
        cmdline.extend(str(s.path) for s in self.sources)
        subprocess.check_call(cmdline)
