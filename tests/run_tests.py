import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase

from minicons import Builder, Dir, Environment, Execution, File, FileSet


class MiniconsTests(TestCase):
    def setUp(self) -> None:
        with ExitStack() as stack:
            tempdir = stack.enter_context(tempfile.TemporaryDirectory())
            self.root = Path(tempdir)

            self.stack = stack.pop_all()

        self.execution = Execution()
        self.env = Environment(path=self.root, execution=self.execution)

    def tearDown(self) -> None:
        self.stack.__exit__(None, None, None)

    def test_file_builder(self) -> None:
        """Tests a builder which outputs a file"""

        class TestBuilder(Builder):
            def get_targets(self) -> File:
                return self.env.file("foo.txt")

            def build(self, target: File) -> None:
                target.path.write_text("Hello, world!")

        builder = TestBuilder(self.env)

        self.execution.build_targets(builder)

        self.assertEqual(
            self.root.joinpath("foo.txt").read_text(),
            "Hello, world!",
        )

    def test_files_builder(self) -> None:
        """Tests a builder which outputs multiple files"""

        class TestBuilder(Builder):
            def get_targets(self) -> FileSet:
                return [
                    self.env.file("foo.txt"),
                    self.env.file("bar.txt"),
                ]

            def build(self, targets: FileSet) -> None:
                for i, file in enumerate(targets):
                    file.path.write_text(f"File {i}")

        builder = TestBuilder(self.env)
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

        class TestBuilder(Builder):
            def get_targets(self) -> Dir:
                return self.env.dir("foo")

            def build(self, target: Dir) -> None:
                target.path.mkdir()
                target.path.joinpath("foo.txt").write_text("foo")
                target.path.joinpath("bar.txt").write_text("bar")

        builder = TestBuilder(self.env)
        self.execution.build_targets(builder)
        self.assertEqual(self.root.joinpath("foo", "foo.txt").read_text(), "foo")
        self.assertEqual(self.root.joinpath("foo", "bar.txt").read_text(), "bar")

        # See that the directory object correctly iterates over the files within the directory
        d = self.env.dir("foo")
        self.assertEqual(
            list(d), [self.env.file("foo/foo.txt"), self.env.file("foo/bar.txt")]
        )
