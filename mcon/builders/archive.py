import tarfile
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ContextManager, Generic, TypeVar, Union

from mcon import Environment, FileLike, FileSetLike, SingleFileBuilder

A = TypeVar("A", bound=ContextManager)


class ArchiveCommon(SingleFileBuilder, Generic[A], ABC):
    def __init__(
        self,
        env: Environment,
        target: FileLike,
        sources: FileSetLike,
        archive_root: Union[str, Path],
    ) -> None:
        super().__init__(env, target)
        self.sources = self.depends_files(sources)
        self.archive_root = self.env.root.joinpath(archive_root)

    def build(self) -> None:
        with self._get_archive_obj() as archive:
            for file in self.sources:
                arcname = str(file.path.relative_to(self.archive_root))
                self._write_to_archive(archive, file.path, arcname)

    @abstractmethod
    def _get_archive_obj(self) -> A:
        pass

    @abstractmethod
    def _write_to_archive(self, archive: A, filename: Path, arcname: str) -> None:
        pass


class ZipBuilder(ArchiveCommon[zipfile.ZipFile]):
    def _get_archive_obj(self) -> zipfile.ZipFile:
        return zipfile.ZipFile(
            self.target.path, mode="w", compression=zipfile.ZIP_DEFLATED
        )

    def _write_to_archive(
        self, archive: zipfile.ZipFile, filename: Path, arcname: str
    ) -> None:
        archive.write(filename, arcname)


class TarBuilder(ArchiveCommon[tarfile.TarFile]):
    def __init__(
        self,
        env: Environment,
        target: FileLike,
        sources: FileSetLike,
        archive_root: Union[str, Path],
        compression: str = "",
    ):
        super().__init__(env, target, sources, archive_root)
        self.compression = compression

    def _get_archive_obj(self) -> tarfile.TarFile:
        return tarfile.open(self.target.path, mode="w:" + self.compression)

    def _write_to_archive(
        self, archive: tarfile.TarFile, filename: Path, arcname: str
    ) -> None:
        archive.add(filename, arcname)
