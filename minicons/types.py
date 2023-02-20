from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Collection,
    Iterable,
    Protocol,
    TypeVar,
    Union,
    runtime_checkable,
)

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
    "SourceLike",
]

ArgTypes = Union[Path, "Entry", "Builder", str]
Args = Union[ArgTypes, Iterable[ArgTypes]]
FileSource = Union[
    "File",
    str,
    Path,
    "SourceLike[File]",
]
FilesSource = Union[
    "File",
    "FileSet",
    "Dir",
    "SourceLike[BuilderType]",
    str,
    Iterable[str],
]
DirSource = Union[
    "Dir",
    "SourceLike[Dir]",
]
E = TypeVar("E", bound="Entry")
FileSet = Collection["File"]
BuilderTargetType = Union["File", "Dir", FileSet]
BuilderType = TypeVar(
    "BuilderType",
    bound=BuilderTargetType,
)


@runtime_checkable
class SourceLike(Protocol[BuilderType]):
    """Any object that has a .target attribute can be used as the source parameter
    to Builder.depends_*() methods. Such objects don't have to explicitly inherit from
    this class.

    """

    target: BuilderType
