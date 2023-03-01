from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Protocol, TypeVar, Union

if TYPE_CHECKING:
    from os import PathLike

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
    "StrPath",
]

StrPath = Union[str, "PathLike[str]"]

# Argument types that can be passed in to register_alias() and build_targets()
ArgTypes = Union[Path, "Node", "SourceLike", str]
Args = Union[ArgTypes, Iterable[ArgTypes]]

# Types that Builder.depends_*() methods take when a builder is declaring a dependency on
# some file, dir, or sourcelike object. The depends_file(), depends_dir(), and depends_files()
# methods will resolve the given object to a File, Dir, or FileSet object respectively.
FileSource = Union[
    "File",
    StrPath,
    "SourceLike[File]",
]
FilesSource = Union[
    "Entry",
    "SourceLike",
    StrPath,
    Iterable["FilesSource"],
]
DirSource = Union[
    "Dir",
    "SourceLike[Dir]",
]

# Types that Environment.file() and Environment.dir() take when constructing a new file or
# dir.
FileArg = Union[StrPath, "File"]
DirArg = Union[StrPath, "Dir"]

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
