import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Collection, Dict, Iterator, List, Optional

if TYPE_CHECKING:
    from minicons.builder import Builder
    from minicons.environment import Environment
    from minicons.types import E


class Entry(ABC):
    """Represents a file or a directory on the filesystem"""

    def __init__(
        self,
        env: "Environment",
        path: Path,
    ):
        self.env = env
        self.path: Path = path

        # Which builder builds this entry
        # This builder's dependencies are implicit dependencies of this entry.
        self.builder: Optional["Builder"] = None

        # Explicit list of additional other entries this one depends on
        self.depends: List["Entry"] = []

        # Flag to show whether this entry has been built yet
        self.built: bool = False

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, type(self)) and self.path == other.path

    def __str__(self) -> str:
        try:
            return str(self.path.relative_to(self.env.root))
        except ValueError:
            return str(self.path)

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        rel_path = str(self)
        return f"{cls_name}({rel_path!r})"

    def derive(self: "E", build_dir_name: str, new_ext: Optional[str] = None) -> "E":
        """Create a derivative file/dir from this entry using Environment.get_build_path()"""
        new_path = self.env.get_build_path(self.path, build_dir_name, new_ext)

        return self.env.create_entry(new_path, type(self))

    def prepare(self) -> None:
        """Hook for the entry to do anything it may need to do before being built

        Called right before its builder is called.
        """
        # Make sure the parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """Returns any metadata this entry should use to compare whether it has changed"""
        ...

    @abstractmethod
    def remove(self) -> None:
        """Removes this entry from the filesystem. Called before building this entry"""
        ...


class File(Entry):
    def get_metadata(self) -> Dict[str, Any]:
        stat_result = os.stat(self.path)
        return {
            "mtime": stat_result.st_mtime_ns,
            "mode": stat_result.st_mode,
            "size": stat_result.st_size,
        }

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)


class Dir(Entry, Collection["File"]):
    def __init__(self, env: "Environment", path: Path, glob: str = "**/*"):
        super().__init__(env, path)
        self.glob_pattern = glob

    def __iter__(self) -> Iterator["File"]:
        if not self.built:
            raise RuntimeError("Cannot iterate over directory before it's built")
        for path in self.path.glob(self.glob_pattern):
            if path.is_file():
                yield self.env.file(path)

    def __contains__(self, item: Any) -> bool:
        return any(item == d for d in self)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def get_metadata(self) -> Dict[str, Any]:
        stat_result = os.stat(self.path)
        metadata: Dict[str, Any]
        metadata = {
            "mode": stat_result.st_mode,
            "files": {},
        }

        file_list: List["File"] = list(self)
        for file in file_list:
            file_metadata = file.get_metadata()
            metadata["files"][str(file.path)] = file_metadata
        return metadata

    def remove(self) -> None:
        if self.path.is_dir():
            shutil.rmtree(self.path)
