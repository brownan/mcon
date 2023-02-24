from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Protocol, TypeVar, Union, runtime_checkable

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
]

ArgTypes = Union[Path, "Node", "SourceLike", str]
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
    Iterable[Union["File", "Dir", "FileSet", "SourceLike"]],
    "SourceLike",
]
DirSource = Union[
    "Dir",
    "SourceLike[Dir]",
]
E = TypeVar("E", bound="Entry")

SourceType = TypeVar(
    "SourceType",
    bound=Union["File", "Dir", "FileSet"],
    covariant=True,
)


@runtime_checkable
class SourceLike(Protocol[SourceType]):
    """Any object that has a .target attribute can be used as the source parameter
    to Builder.depends_*() methods. Such objects don't have to explicitly inherit from
    this class.

    """

    # `target` must be read-only in order for SourceLike to be covariant in SourceType
    @property
    def target(self) -> SourceType:
        raise NotImplementedError
