from typing import TYPE_CHECKING, Iterable, Protocol, TypeVar, Union

if TYPE_CHECKING:
    from os import PathLike

    from mcon.entry import Dir, Entry, File, FileSet, Node

__all__ = [
    "TargetTypes",
    "FileLike",
    "FileSetLike",
    "DirLike",
    "E",
    "SourceType",
    "SourceLike",
    "StrPath",
]

StrPath = Union[str, "PathLike[str]"]

# Argument types that can be passed in to register_alias() and build_targets()
TargetTypes = Union[StrPath, "Node", "SourceLike", Iterable["TargetTypes"]]

# These types are the types accepted by various methods and are translated to File,
# FileSet, or Dir objects respectively.
#
# FileLike is accepted by Environment.file() and Builder.depends_file()
# FileSetLike is accepted by Builder.depends_files() and FileSet.add()
# DirLike is accepted by Environment.dir() and Builder.depends_dir()
FileLike = Union[
    "File",
    StrPath,
    "SourceLike[File]",
]
FileSetLike = Union[
    "Entry",
    "SourceLike",
    StrPath,
    Iterable["FileSetLike"],
]
DirLike = Union[
    "Dir",
    StrPath,
    "SourceLike[Dir]",
]

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

    target: SourceType | "SourceLike[SourceType]"
