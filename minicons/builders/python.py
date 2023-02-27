import base64
import csv
import dataclasses
import hashlib
import os.path
import re
from configparser import ConfigParser
from email.message import Message
from os import PathLike
from pathlib import Path
from typing import List, Tuple, Union

import packaging.requirements
import packaging.tags
import packaging.utils
import packaging.version
import toml

from minicons import Builder, Environment, FileSet, SingleFileBuilder
from minicons.builders.archive import TarBuilder, ZipBuilder
from minicons.builders.install import InstallFiles
from minicons.types import DirArg, FileArg, FilesSource


def urlsafe_b64encode(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


DIST_NAME_RE = re.compile(
    "^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", flags=re.IGNORECASE
)
EXTRA_RE = re.compile("^([a-z0-9]|[a-z0-9]([a-z0-9-](?!--))*[a-z0-9])$")


class PyProjectError(Exception):
    pass


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


def parse_pyproject_toml(file: PathLike) -> PyProject:
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


class Wheel:
    def __init__(self, env: Environment, tag: str, dist_dir: Union[str, Path] = "dist"):
        self.env = env

        # Wheel configuration
        self.tag = tag
        self.tags = packaging.tags.parse_tag(tag)
        self.root_is_purelib = tag.endswith("-none-any")

        # Parse pyproject.toml file in the current directory
        self.pyproject = parse_pyproject_toml(self.env.root.joinpath("pyproject.toml"))
        self.project_metadata = self.pyproject.project_metadata
        self.tool_metadata = self.pyproject.tool_metadata
        self.name = self.pyproject.name
        self.version = self.pyproject.version

        dist_filename = self.pyproject.dist_filename
        data_dir_name = f"{dist_filename}-{self.version}.dist-info"

        wheel_name = "{}-{}-{}.whl".format(
            dist_filename,
            self.version,
            self.tag,
        )

        self.wheel_build_dir = self.env.build_root.joinpath("wheel")
        self.wheel_data_dir = self.wheel_build_dir.joinpath(data_dir_name)
        dist_dir = env.root.joinpath(dist_dir)

        self.wheel_fileset = FileSet(env)
        self.manifest_fileset = FileSet(env)
        self.wheel = ZipBuilder(
            env,
            env.file(dist_dir / wheel_name),
            self.wheel_fileset,
            self.wheel_build_dir,
        )

        metadata_dir = WheelMetadataBuilder(env, self.wheel_data_dir, tag, self.pyproject)
        self.wheel_fileset.add(metadata_dir)
        self.manifest_fileset.add(metadata_dir)

        self.wheel_fileset.add(
            WheelManifestBuilder(
                env, self.wheel_build_dir, self.wheel_data_dir, self.manifest_fileset
            )
        )

        self.target = self.wheel

    def add_sources(
        self,
        sources: FilesSource,
        relative_to: str = "",
    ) -> None:
        fileset = InstallFiles(self.env, self.wheel_build_dir, sources, relative_to)
        self.wheel_fileset.add(fileset)
        self.manifest_fileset.add(fileset)

    def add_data(
        self,
        sources: FilesSource,
        category: str,
        relative_to: str = "",
    ) -> None:
        fileset = InstallFiles(
            self.env, self.wheel_data_dir / category, sources, relative_to
        )
        self.wheel_fileset.add(fileset)


class SDist:
    def __init__(self, env: Environment, dist_dir: Union[str, Path] = "dist"):
        self.env = env
        dist_dir = env.root.joinpath(dist_dir)

        self.pyproject = parse_pyproject_toml(self.env.root.joinpath("pyproject.toml"))
        self.version = self.pyproject.version
        dist_filename = self.pyproject.dist_filename

        sdist_build_dir = env.build_root.joinpath("sdist")
        self.sdist_build_root = sdist_build_dir / f"{dist_filename}-{self.version}"
        self.sdist_fileset = FileSet(env)
        self.target = TarBuilder(
            env,
            env.file(dist_dir.joinpath(f"{dist_filename}-{self.version}.tar.gz")),
            self.sdist_fileset,
            sdist_build_dir,
            compression="gz",
        )
        self.sdist_fileset.add(
            CoreMetadataBuilder(env, self.sdist_build_root / "PKG-INFO", self.pyproject)
        )

    def add_sources(
        self,
        sources: FilesSource,
        relative_to: str = "",
    ) -> None:
        destdir = self.sdist_build_root
        fileset = InstallFiles(self.env, destdir, sources, relative_to)
        self.sdist_fileset.add(fileset)


class CoreMetadataBuilder(SingleFileBuilder):
    def __init__(self, env: Environment, target: FileArg, pyproject: PyProject):
        super().__init__(env, target)
        self.pyproject = pyproject
        self.core_metadata, additital_deps = build_core_metadata(pyproject)
        self.depends_file(pyproject.file)
        self.depends_files(additital_deps)

    def build(self) -> None:
        self.target.path.write_text(self.core_metadata)


class WheelMetadataBuilder(Builder):
    def __init__(self, env: Environment, target: DirArg, tag: str, pyproject: PyProject):
        super().__init__(env)
        dir_target = self.register_target(self.env.dir(target))
        self.tag = tag
        self.pyproject = pyproject
        self.depends_file(pyproject.file)

        # Core metadata has to be built /after/ the WheelMetadataBuilder, since it depends
        # on the directory being built
        core_metadata = CoreMetadataBuilder(env, dir_target.path / "METADATA", pyproject)
        core_metadata.depends_dir(dir_target)
        self.target = FileSet(env, [dir_target, core_metadata])
        self.dir_target = dir_target

    def build(self) -> None:
        tag = self.tag
        datadir = self.dir_target.path

        datadir.mkdir(exist_ok=True)

        root_is_purelib = tag.endswith("-none-any")

        # Build wheel metadata
        msg = Message()
        msg["Wheel-Version"] = "1.0"
        msg["Generator"] = "minicons"
        msg["Root-Is-Purelib"] = str(root_is_purelib).lower()
        for t in packaging.tags.parse_tag(tag):
            msg["Tag"] = str(t)
        datadir.joinpath("WHEEL").write_text(str(msg))

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

        with datadir.joinpath("entry_points.txt").open("w", encoding="utf-8") as f:
            ini.write(f)


class WheelManifestBuilder(Builder):
    def __init__(
        self,
        env: Environment,
        wheel_build_dir: Path,
        wheel_data_dir: Path,
        wheel_fileset: FileSet,
    ):
        super().__init__(env)
        self.wheel_fileset = self.depends_files(wheel_fileset)
        self.wheel_build_dir = wheel_build_dir
        self.target = self.register_target(self.env.file(wheel_data_dir / "RECORD"))

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