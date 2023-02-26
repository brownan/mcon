from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Protocol, TypeVar, Union

if TYPE_CHECKING:
    from minicons import Dir, Entry, File, FileSet, Node

__all__ = [
    "ArgTypes",
    "Args",
    "FileSource",
    "FilesSource",
    "DirSource",
    "E",
    "SourceType",
    "SourceLike",
    "FileArg",
    "DirArg",
]

# Argument types that can be passed in to register_alias() and build_targets()
ArgTypes = Union[Path, "Node", "SourceLike", str]
Args = Union[ArgTypes, Iterable[ArgTypes]]

# Types that Builder.depends_*() methods take
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
    Iterable[Union["File", "Dir", "FileSet", "SourceLike"]],
    "SourceLike",
]
DirSource = Union[
    "Dir",
    "SourceLike[Dir]",
]

# Types that Environment.file() and Environment.dir() take when constructing a new
FileArg = Union[str, "Path", "File"]
DirArg = Union[str, "Path", "Dir"]

E = TypeVar("E", bound="Entry")

SourceType = TypeVar(
    "SourceType",
    bound=Union["File", "Dir", "FileSet"],
)


class SourceLike(Protocol[SourceType]):
    """Any object that has a .target attribute can be used as the source parameter
    to Builder.depends_*() methods. Such objects don't have to explicitly inherit from
    this class.


    """

    target: SourceType
