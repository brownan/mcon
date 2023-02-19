import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase

from minicons.builder import Builder
from minicons.entry import Dir, File
from minicons.environment import Environment
from minicons.execution import Execution
from minicons.types import FileSet, FileSource


class MiniconsTests(TestCase):
    def setUp(self) -> None:
        with ExitStack() as stack:
            tempdir = stack.enter_context(tempfile.TemporaryDirectory())
            self.root = Path(tempdir)

            self.stack = stack.pop_all()

        self.execution = Execution(self.root)
        self.env = Environment(root=self.root, execution=self.execution)

    def tearDown(self) -> None:
        self.stack.__exit__(None, None, None)

    def test_file_builder(self) -> None:
        """Tests a builder which outputs a file"""

        class TestBuilder(Builder[File]):
            def build(self) -> None:
                self.target.path.write_text("Hello, world!")

        builder = TestBuilder(self.env, self.env.file("foo.txt"))

        self.execution.build_targets(builder)

        self.assertEqual(
            self.root.joinpath("foo.txt").read_text(),
            "Hello, world!",
        )

        # Make sure this file isn't built again if re-run
        prepared_build = self.execution.prepare_build(builder)
        self.assertFalse(prepared_build.to_build)

    def test_files_builder(self) -> None:
        """Tests a builder which outputs multiple files"""

        class TestBuilder(Builder[FileSet]):
            def build(self) -> None:
                for i, file in enumerate(self.target):
                    file.path.write_text(f"File {i}")

        builder = TestBuilder(
            self.env,
            [
                self.env.file("foo.txt"),
                self.env.file("bar.txt"),
            ],
        )
        self.execution.build_targets(builder)
        self.assertEqual(
            self.root.joinpath("foo.txt").read_text(),
            "File 0",
        )
        self.assertEqual(
            self.root.joinpath("bar.txt").read_text(),
            "File 1",
        )

    def test_dir_builder(self) -> None:
        """Tests a builder which outputs a directory"""

        class TestBuilder(Builder[Dir]):
            def build(self) -> None:
                self.target.path.mkdir()
                self.target.path.joinpath("foo.txt").write_text("foo")
                self.target.path.joinpath("bar.txt").write_text("bar")

        builder = TestBuilder(self.env, self.env.dir("foo"))
        self.execution.build_targets(builder)
        self.assertEqual(self.root.joinpath("foo", "foo.txt").read_text(), "foo")
        self.assertEqual(self.root.joinpath("foo", "bar.txt").read_text(), "bar")

        # See that the directory object correctly iterates over the files within the directory
        d = self.env.dir("foo")
        self.assertEqual(
            list(d), [self.env.file("foo/foo.txt"), self.env.file("foo/bar.txt")]
        )

    def test_file_dependency(self) -> None:
        """Tests the dependency checker"""

        class TestBuilder(Builder[File]):
            def __init__(
                self, env: Environment, target: File, source: FileSource
            ) -> None:
                super().__init__(env, target)
                self.source = self.depends_file(source)

            def build(self) -> None:
                self.target.path.write_text(self.source.path.read_text())

        inpath = Path(self.root.joinpath("foo.txt"))
        infile = self.env.file(inpath)
        outfile = infile.derive("bdir")
        outpath = outfile.path

        inpath.write_text("Version 1")
        os.utime(inpath, (1, 1))

        builder = TestBuilder(self.env, outfile, inpath)
        self.execution.build_targets(builder)

        self.assertEqual(outpath.read_text(), "Version 1")

        # No rebuild here
        prepared = self.execution.prepare_build(builder)
        self.assertFalse(prepared.to_build)
        self.assertEqual(prepared.dependencies[outfile], [infile])

        inpath.write_text("Version 2")
        # Set the mtime to something later. Just using the default system mtimes isn't
        # reliable if the tests run too fast
        os.utime(inpath, (100, 100))
        prepared = self.execution.prepare_build(builder)
        self.assertEqual(prepared.to_build, {outfile})

        self.execution.build_targets(prepared_build=prepared)
        self.assertEqual(outpath.read_text(), "Version 2")
