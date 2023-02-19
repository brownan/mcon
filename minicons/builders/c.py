import shlex
import subprocess
from typing import Iterable, List, Optional, Union

from minicons import Builder, Environment, File, FilesSource


class SharedLibrary(Builder[File]):
    def __init__(
        self,
        env: Environment,
        target: File,
        sources: FilesSource,
        cc: str = "cc",
        cflags: Union[str, Iterable[str], None] = None,
        include_dirs: Optional[Iterable[str]] = None,
        lib_dirs: Optional[Iterable[str]] = None,
    ):
        super().__init__(env)
        self.sources = self.depends_files(sources)
        self.target = target
        self.cc: str = cc
        self.cflags: List[str]
        if isinstance(cflags, str):
            self.cflags = shlex.split(cflags)
        elif cflags is None:
            self.cflags = []
        else:
            self.cflags = list(cflags)
        self.include_dirs = list(include_dirs) if include_dirs else []
        self.lib_dirs = list(lib_dirs) if lib_dirs else []

    def get_targets(self) -> File:
        return self.target

    def build(self, target: File) -> None:
        cmdline = [
            self.cc,
            "-shared",
            "-o",
            str(target.path),
        ]
        for incdir in self.include_dirs:
            cmdline.extend(["-I", incdir])
        for libdir in self.lib_dirs:
            cmdline.extend(["-L", libdir])
        cmdline.extend(self.cflags)
        cmdline.extend(str(s.path) for s in self.sources)
        subprocess.check_call(cmdline)
