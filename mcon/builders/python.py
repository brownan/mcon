from __future__ import annotations

import base64
import csv
import dataclasses
import hashlib
import os.path
import re
from configparser import ConfigParser
from email.message import Message
from pathlib import Path
from typing import List, Sequence, Tuple, Union

import packaging.requirements
import packaging.tags
import packaging.utils
import packaging.version
import toml

from mcon import Builder, Environment, FileSet, SingleFileBuilder
from mcon.builder import Command
from mcon.builders.archive import TarBuilder, ZipBuilder
from mcon.builders.install import Install, InstallFiles
from mcon.types import DirLike, FileLike, FileSetLike, StrPath


def urlsafe_b64encode(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


DIST_NAME_RE = re.compile(
    "^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", flags=re.IGNORECASE
)
EXTRA_RE = re.compile("^([a-z0-9]|[a-z0-9]([a-z0-9-](?!--))*[a-z0-9])$")


class PyProjectError(Exception):
    pass


def get_binary_tag() -> str:
    """Gets the most specific binary tag for the current machine"""
    # This looks through sys_tags() for the first tag that doesn't use the manylinux platform.
    # Why do we skip the manylinux platform?
    #
    # sys_tags() lists tags compatible with the current system in order. since
    # the generic linux_x86_64 platform is not a precise enough tag to guarantee compatibility,
    # the packaging library considers "manylinux" to be a higher priority for installation
    # candidates.
    #
    # However, we are not choosing an installation candidate, we want to find a tag for the
    # distribution being built, so our priorities are a bit different. Instead, it makes sense
    # for linux builds to use the imprecise linux_x86_64 (or similar) platform, since
    # we cannot programmatically guarantee platform compatibility with the manylinux spec.
    # In the future, maybe there is some way to incorporate functionality from the "auditwheel"
    # tool to automatically determine a more precise linux platform.
    return str(
        next(tag for tag in packaging.tags.sys_tags() if "manylinux" not in tag.platform)
    )


def get_pure_tag() -> str:
    """Gets the tag for a pure-python wheel with no platform specific aspects compatible
    with the current python version and up

    """
    interp_tag = f"py{packaging.tags.interpreter_version()}"
    return f"{interp_tag}-none-any"


@dataclasses.dataclass
class PyProject:
    """Holds information about a parsed pyproject.toml file"""

    # Validate project name
    name: str
    # Validated version
    version: str
    # The distribution name component to be used in filenames
    dist_filename: str

    # Full deserialized project table
    project_metadata: dict
    # Tool table
    tool_metadata: dict

    # The filename that it was parsed from, for dependency tracking
    file: Path


def parse_pyproject_toml(file: StrPath) -> PyProject:
    """Reads in a pyproject.toml file, does some minimal normalization and validation"""
    parsed = toml.load(open(file))
    project_metadata = parsed["project"]
    try:
        tool_metadata = parsed["tool"]
    except KeyError:
        tool_metadata = {}

    # Validate the name
    name = project_metadata["name"]
    if not DIST_NAME_RE.match(name):
        raise PyProjectError(
            "Distribution name must consist of only ASCII letters, numbers, period, "
            "underscore, and hyphen. It must start and end with a letter or number. "
            f"Was {name!r}"
        )

    # The distribution name component to be used in filenames
    dist_filename = packaging.utils.canonicalize_name(name).replace("-", "_")

    # Check if the version is valid and normalize it
    version = str(packaging.version.parse(project_metadata["version"]))
    project_metadata["version"] = version

    return PyProject(
        name=name,
        version=version,
        dist_filename=dist_filename,
        project_metadata=project_metadata,
        tool_metadata=tool_metadata,
        file=Path(file).resolve(),
    )


def build_core_metadata(pyproject: PyProject) -> Tuple[str, List[Path]]:
    """Builds the core metadata from the parsed pyproject.toml data"""
    # Reference: https://packaging.python.org/en/latest/specifications/core-metadata/
    # and: https://packaging.python.org/en/latest/specifications/declaring-project-metadata/
    sources: List[Path] = [pyproject.file]
    msg = Message()
    metadata = pyproject.project_metadata

    # Required metadata
    # This routine writes metadata compatible with version 2.3, but the pypi index only
    # currently supports 2.1 as of Feb 2023.
    # See https://github.com/pypi/warehouse/pull/11380
    # Additionally, the pkginfo library used by the twine utility only supports up to 2.2
    # Things should still be compatible by the following logic:
    # New in 2.2 is the Dynamic field, which this metadata writer doesn't use.
    # New in 2.3 was a required unambiguous format for extra names, to replace previous
    # normalization rules. This metadata writer enforces the extra name format and therefore
    # extra names are always unambiguous, making it compatible with older readers.
    msg["Metadata-Version"] = "2.1"
    msg["Name"] = pyproject.name
    msg["Version"] = pyproject.version

    # Optional metadata
    if "description" in metadata:
        msg["Summary"] = metadata["description"]
    if "requires-python" in metadata:
        msg["Requires-Python"] = metadata["requires-python"]

    # Readme field. May be a string referencing a file, or a table specifying a content
    # type and either a file or text.
    if "readme" in metadata:
        readme = metadata["readme"]
        if isinstance(readme, str):
            filename = readme
            contenttype = None
            content = open(filename, "r", encoding="utf-8").read()
        else:
            assert isinstance(readme, dict)
            if "file" and "text" in readme:
                raise PyProjectError(
                    f'"file" and "text" keys are mutually exclusive in {pyproject.file}'
                    f" project.readme table"
                )
            if "file" in readme:
                filename = readme["file"]
                contenttype = readme.get("content-type")
                encoding = readme.get("encoding", "utf-8")
                content = open(filename, "r", encoding=encoding).read()
            else:
                filename = None
                try:
                    contenttype = readme["content-type"]
                except KeyError as e:
                    raise PyProjectError(
                        f"Missing content-type key in {pyproject.file} project.readme table"
                    ) from e
                content = readme["text"]
        if contenttype is None:
            assert filename
            ext = os.path.splitext(filename)[1].lower()
            try:
                contenttype = {
                    ".md": "text/markdown",
                    ".rst": "text/x-rst",
                    ".txt": "text/plain",
                }[ext]
            except KeyError:
                raise PyProjectError(
                    f"Unknown readme file type {filename}. "
                    f'Specify an explicit "content-type" key in the {pyproject.file} '
                    f"project.readme table"
                )
        if filename:
            sources.append(Path(filename).resolve())
        msg["Description-Content-Type"] = contenttype
        msg.set_payload(content)

    # License must be a table with either a "text" or a "file" key. Either the text
    # string or the file's contents are added under the License core metadata field.
    # If I'm interpreting the spec right, the entire license is stuffed into this single
    # field. I wonder if the spec intended to e.g. include the entire GPL here?
    # I think the intent was to only use this field if the license is something
    # non-standard. Otherwise, use the appropriate classifier.
    # See https://packaging.python.org/en/latest/specifications/declaring-project-metadata/#license
    if "license" in metadata:
        filename = metadata["license"].get("file")
        content = metadata["license"].get("text")
        if filename and content:
            raise PyProjectError(
                f'"file" and "text" keys are mutually exclusive in {pyproject.file} '
                f"project.license table"
            )
        if filename:
            content = open(filename, "r", encoding="utf-8").read()
            sources.append(Path(filename).resolve())
        msg["License"] = content

    if "authors" in metadata:
        _write_contacts(msg, "Author", "Author-Email", metadata["authors"])
    if "maintainers" in metadata:
        _write_contacts(msg, "Maintainer", "Maintainer-Email", metadata["maintainers"])

    if "keywords" in metadata:
        msg["Keywords"] = ",".join(metadata["keywords"])

    if "classifiers" in metadata:
        for c in metadata["classifiers"]:
            msg["Classifier"] = c

    if "urls" in metadata:
        for label, url in metadata["urls"].items():
            msg["Project-URL"] = f"{label}, {url}"

    if "dependencies" in metadata:
        for dep in metadata["dependencies"]:
            # Validate and normalize
            dep = str(packaging.requirements.Requirement(dep))
            msg["Requires-Dist"] = dep

    if "optional-dependencies" in metadata:
        for extra_name, dependencies in metadata["optional-dependencies"].items():
            if not EXTRA_RE.match(extra_name):
                raise PyProjectError(f'Invalid extra name "{extra_name}"')
            msg["Provides-Extra"] = extra_name
            for dep in dependencies:
                # Validate and normalize
                dep = str(packaging.requirements.Requirement(dep))
                msg["Requires-Dist"] = f"{dep}; extra == '{extra_name}'"

    return str(msg), sources


class Distribution:
    """Sets up the builders for building a wheel and sdist from a python distribution

    This is the main interface for building wheels and source distributions. Create a
    Distribution object and then use the .wheel() and .sdist() methods to return a wheel
    and sdist target respectively. All the other supporting builders are set up
    automatically.
    """

    def __init__(self, env: Environment):
        self.env = env
        self.wheel_dist_dir = env.root / self.env.get("WHEEL_DIST_DIR", "dist")
        self.sdist_dist_dir = env.root / self.env.get("SDIST_DIST_DIR", "dist")
        self.editable_dist_dir = env.root / self.env.get(
            "EDITABLE_DIST_DIR", env.build_root / "wheel-editable"
        )

        # Parse pyproject.toml file in the current directory
        self.pyproject = parse_pyproject_toml(self.env.root.joinpath("pyproject.toml"))
        self.project_metadata = self.pyproject.project_metadata
        self.tool_metadata = self.pyproject.tool_metadata
        self.name = self.pyproject.name
        self.version = self.pyproject.version

        # Core metadata is used for both source and wheel builds
        self.core_metadata = CoreMetadataBuilder(
            env, env.get_build_path("METADATA", ""), self.pyproject
        )

    def wheel(self, tag: str) -> Wheel:
        """Returns a wheel builder"""
        return Wheel(
            self.env,
            self.wheel_dist_dir,
            self.pyproject,
            tag,
            self.core_metadata,
            f"wheel.{tag}",
        )

    def sdist(self) -> SDist:
        """Returns an sdist builder"""
        return SDist(self.env, self.sdist_dist_dir, self.pyproject, self.core_metadata)

    def editable(self, tag: str, paths: Union[str, Sequence[str]]) -> FileLike:
        """Returns an editable wheel builder"""
        if isinstance(paths, str):
            paths = [paths]

        # This is basically just a wheel except with a single .pth file in it. So we set
        # up a wheel just like normal but only add the one file to it.
        wheel = Wheel(
            self.env,
            self.editable_dist_dir,
            self.pyproject,
            tag,
            self.core_metadata,
            build_dir_name="wheel-editable",
        )

        pthfile = ""
        for path in paths:
            abspath = self.env.root.joinpath(path).resolve()
            pthfile += str(abspath) + "\n"

        pthname = f"{self.pyproject.dist_filename}-{self.version}.pth"

        file = Command(
            self.env,
            self.env.file(wheel.wheel_build_dir / pthname),
            None,
            lambda f: f.path.write_text(pthfile),
        )
        wheel.wheel_fileset.add(file)
        wheel.manifest_fileset.add(file)

        return wheel.target


class Wheel:
    def __init__(
        self,
        env: Environment,
        distdir: StrPath,
        pyproject: PyProject,
        tag: str,
        core_metadata: FileLike,
        build_dir_name: str,
    ):
        self.env = env

        # Wheel configuration
        self.tag = tag
        self.tags = packaging.tags.parse_tag(tag)
        self.root_is_purelib = tag.endswith("-none-any")
        version = pyproject.version

        dist_filename = pyproject.dist_filename
        data_dir_name = f"{dist_filename}-{version}.data"
        dist_info_name = f"{dist_filename}-{version}.dist-info"

        wheel_name = "{}-{}-{}.whl".format(
            dist_filename,
            version,
            self.tag,
        )

        self.wheel_build_dir = self.env.build_root / build_dir_name
        self.dist_info_dir = self.wheel_build_dir / dist_info_name
        self.data_dir = self.wheel_build_dir / data_dir_name

        self.wheel_fileset = FileSet(env)
        self.manifest_fileset = FileSet(env)
        self.target = ZipBuilder(
            env,
            env.file(Path(distdir) / wheel_name),
            self.wheel_fileset,
            self.wheel_build_dir,
        )

        metadata_dir = WheelMetadataBuilder(
            env, self.dist_info_dir, tag, pyproject, core_metadata
        )
        self.wheel_fileset.add(metadata_dir)
        self.manifest_fileset.add(metadata_dir)

        self.wheel_fileset.add(
            WheelManifestBuilder(
                env, self.wheel_build_dir, self.dist_info_dir, self.manifest_fileset
            )
        )

    def add_sources(
        self,
        sources: FileSetLike,
        *,
        relative_to: StrPath = "",
        prefix: StrPath = "",
    ) -> None:
        fileset = InstallFiles(
            self.env,
            self.wheel_build_dir / prefix,
            sources,
            relative_to=relative_to,
        )
        self.wheel_fileset.add(fileset)
        self.manifest_fileset.add(fileset)

    def add_data(
        self,
        sources: FileSetLike,
        category: str,
        *,
        relative_to: str = "",
        prefix: StrPath = "",
    ) -> None:
        fileset = InstallFiles(
            self.env,
            self.data_dir / category / prefix,
            sources,
            relative_to=relative_to,
        )
        self.wheel_fileset.add(fileset)
        self.manifest_fileset.add(fileset)


class SDist:
    def __init__(
        self,
        env: Environment,
        dist_dir: StrPath,
        pyproject: PyProject,
        core_metadata: FileLike,
    ):
        self.env = env
        dist_dir = env.root.joinpath(dist_dir)

        version = pyproject.version
        dist_filename = pyproject.dist_filename

        sdist_build_dir = env.build_root.joinpath("sdist")
        self.sdist_build_root = sdist_build_dir / f"{dist_filename}-{version}"
        self.sdist_fileset = FileSet(env)
        self.target = TarBuilder(
            env,
            env.file(dist_dir.joinpath(f"{dist_filename}-{version}.tar.gz")),
            self.sdist_fileset,
            sdist_build_dir,
            compression="gz",
        )
        self.sdist_fileset.add(
            Install(
                env,
                self.sdist_build_root / "PKG-INFO",
                core_metadata,
            )
        )

    def add_sources(
        self,
        sources: FileSetLike,
        *,
        relative_to: str = "",
        prefix: StrPath = "",
    ) -> None:
        destdir = self.sdist_build_root / prefix
        fileset = InstallFiles(self.env, destdir, sources, relative_to=relative_to)
        self.sdist_fileset.add(fileset)


class CoreMetadataBuilder(SingleFileBuilder):
    def __init__(self, env: Environment, target: FileLike, pyproject: PyProject):
        super().__init__(env, target)
        self.pyproject = pyproject
        self.core_metadata, additional_deps = build_core_metadata(pyproject)
        self.depends_file(pyproject.file)
        self.depends_files(additional_deps)

    def build(self) -> None:
        self.target.path.write_text(self.core_metadata)


class WheelMetadataBuilder(Builder):
    def __init__(
        self,
        env: Environment,
        dist_info_dir: DirLike,
        tag: str,
        pyproject: PyProject,
        core_metadata: FileLike,
    ):
        super().__init__(env)
        self.tag = tag
        self.pyproject = pyproject
        self.depends_file(pyproject.file)

        # Core metadata has to be built /after/ the WheelMetadataBuilder, since it depends
        # on the directory being built
        self.core_metadata = self.depends_file(core_metadata)

        self.dist_info_dir = env.dir(dist_info_dir)

        self.target = [
            self.register_target(self.env.file(self.dist_info_dir.path / name))
            for name in [
                "METADATA",
                "WHEEL",
                "entry_points.txt",
            ]
        ]

    def build(self) -> None:
        tag = self.tag
        dist_info_dir = self.dist_info_dir.path

        dist_info_dir.mkdir(exist_ok=True)

        # Copy core metadata
        dist_info_dir.joinpath("METADATA").write_text(self.core_metadata.path.read_text())

        root_is_purelib = tag.endswith("-none-any")

        # Build wheel metadata
        msg = Message()
        msg["Wheel-Version"] = "1.0"
        msg["Generator"] = "mcon"
        msg["Root-Is-Purelib"] = str(root_is_purelib).lower()
        for t in packaging.tags.parse_tag(tag):
            msg["Tag"] = str(t)
        dist_info_dir.joinpath("WHEEL").write_text(str(msg))

        # Build entry points file
        metadata = self.pyproject.project_metadata
        groups = {}
        if "scripts" in metadata:
            groups["console_scripts"] = metadata["scripts"]

        if "gui-scripts" in metadata:
            groups["gui_scripts"] = metadata["gui-scripts"]

        if "entry-points" in metadata:
            for group, items in metadata["entry-points"].items():
                if group in ("scripts", "gui-scripts"):
                    raise PyProjectError(
                        f"Invalid {self.pyproject.file} table "
                        f"project.entry-points.{group}. Use "
                        f"project.{group} instead"
                    )
                groups[group] = items

        ini = ConfigParser()
        for group, items in groups.items():
            ini.add_section(group)
            for key, val in items.items():
                ini[group][key] = val

        with dist_info_dir.joinpath("entry_points.txt").open("w", encoding="utf-8") as f:
            ini.write(f)


class WheelManifestBuilder(Builder):
    def __init__(
        self,
        env: Environment,
        wheel_build_dir: Path,
        wheel_dist_info_dir: Path,
        wheel_fileset: FileSet,
    ):
        super().__init__(env)
        self.wheel_fileset = self.depends_files(wheel_fileset)
        self.wheel_build_dir = wheel_build_dir
        self.target = self.register_target(self.env.file(wheel_dist_info_dir / "RECORD"))

    def build(self) -> None:
        with self.target.path.open("w", newline="") as outfile:
            writer = csv.writer(outfile)
            for f in self.wheel_fileset:
                path_str = f.relative_to(self.wheel_build_dir)
                data = f.path.read_bytes()
                size = len(data)
                digest = hashlib.sha256(data).digest()
                digest_str = "sha256=" + (urlsafe_b64encode(digest).decode("ascii"))
                writer.writerow([path_str, digest_str, str(size)])

            writer.writerow(
                [
                    self.target.relative_to(self.wheel_build_dir),
                    "",
                    "",
                ]
            )


def _write_contacts(
    msg: Message, header_name: str, header_email: str, contacts: List[dict]
) -> None:
    # Reference
    # https://packaging.python.org/en/latest/specifications/declaring-project-metadata/#authors-maintainers
    names = []
    emails = []
    for contact in contacts:
        name = contact.get("name")
        email = contact.get("email")
        if not name and not email:
            raise ValueError(
                'At least one of "name" or "email" must be specified for each author '
                "and maintainer"
            )
        elif name and not email:
            names.append(name)
        elif email and not name:
            emails.append(email)
        else:
            emails.append(f"{name} <{email}>")

    if names:
        msg[header_name] = ", ".join(names)
    if emails:
        msg[header_email] = ", ".join(emails)
