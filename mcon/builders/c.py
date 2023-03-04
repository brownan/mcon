import dataclasses
import shlex
import subprocess
from typing import Collection, List, Optional, Sequence

from mcon import Environment, File, FileLike, FileSetLike
from mcon.builder import SingleFileBuilder


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


def get_default_compiler_config() -> CompilerConfig:
    return CompilerConfig()


class CompiledObject(SingleFileBuilder):
    def __init__(
        self,
        env: Environment,
        target: FileLike,
        sources: FileSetLike,
        compiler_config: Optional[CompilerConfig] = None,
    ):
        super().__init__(env, target)
        self.sources = self.depends_files(sources)
        self.compiler_config = compiler_config or get_default_compiler_config()

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


class Program(SingleFileBuilder):
    def __init__(
        self,
        env: Environment,
        target: FileLike,
        sources: FileSetLike,
        compiler_config: Optional[CompilerConfig] = None,
    ):
        super().__init__(env, target)
        self.sources = self.depends_files(sources)
        self.compiler_config = compiler_config or get_default_compiler_config()

    def __str__(self) -> str:
        return f"Linking {self.target}"

    def get_targets(self) -> File:
        return self.target

    def get_cmdline(self) -> List[str]:
        conf = self.compiler_config
        cmdline = shlex.split(conf.ld)
        cmdline += [
            "-o",
            str(self.target.path),
        ]
        cmdline += conf.ldflags
        for libdir in conf.lib_dirs:
            cmdline.extend(["-L", libdir])
        cmdline.extend(str(s.path) for s in self.sources)
        return cmdline

    def build(self) -> None:
        cmdline = self.get_cmdline()
        subprocess.check_call(cmdline)


class SharedLibrary(Program):
    def get_cmdline(self) -> List[str]:
        cmdline = super().get_cmdline()
        if "-shared" not in cmdline:
            cmdline.append("-shared")
        return cmdline
