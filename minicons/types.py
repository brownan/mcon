from pathlib import Path
from typing import TYPE_CHECKING, Collection, Iterable, TypeVar, Union

if TYPE_CHECKING:
    from minicons import Builder, Dir, Entry, File

__all__ = [
    "ArgTypes",
    "Args",
    "FileSource",
    "FilesSource",
    "DirSource",
    "FileSet",
    "BuilderTargetType",
    "BuilderType",
    "E",
]

ArgTypes = Union[Path, "Entry", "Builder", str]
Args = Union[ArgTypes, Iterable[ArgTypes]]
FileSource = Union[
    "File",
    str,
    Path,
    "Builder[File]",
]
FilesSource = Union[
    "File",
    "FileSet",
    "Dir",
    "Builder[BuilderType]",
    str,
    Iterable[str],
]
DirSource = Union[
    "Dir",
    "Builder[Dir]",
]
FileSet = Collection["File"]
BuilderTargetType = Union["File", "Dir", FileSet]
BuilderType = TypeVar(
    "BuilderType",
    bound=BuilderTargetType,
)
E = TypeVar("E", bound="Entry")
