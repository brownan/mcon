import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase

from mcon.builder import Builder, SingleFileBuilder
from mcon.builders.c import CompilerConfig, SharedLibrary
from mcon.entry import File
from mcon.environment import Environment
from mcon.execution import Execution
from mcon.types import DirLike, FileLike, SourceLike


class Common(TestCase):
    def setUp(self) -> None:
        with ExitStack() as stack:
            tempdir = stack.enter_context(tempfile.TemporaryDirectory())
            self.root = Path(tempdir)

            self.stack = stack.pop_all()

        self.execution = Execution(self.root)
        self.env = Environment(root=self.root, execution=self.execution)

    def tearDown(self) -> None:
        self.stack.__exit__(None, None, None)


class MiniconsTests(Common):
    def test_file_builder(self) -> None:
        """Tests a builder which outputs a file"""

        class TestBuilder(SingleFileBuilder):
            def build(self) -> None:
                self.target.path.write_text("Hello, world!")

        builder: SourceLike[File] = TestBuilder(self.env, self.env.file("foo.txt"))

        self.execution.build_targets(builder)

        self.assertEqual(
            self.root.joinpath("foo.txt").read_text(),
            "Hello, world!",
        )

        # Make sure this file isn't built again if re-run
        prepared_build = self.execution.prepare_build(builder)
        self.assertFalse(prepared_build.get_to_build())

    def test_files_builder(self) -> None:
        """Tests a builder which outputs multiple files"""

        class TestBuilder(Builder):
            def __init__(self, env: Environment, f1: FileLike, f2: FileLike):
                super().__init__(env)
                self.f1 = self.register_target(env.file(f1))
                self.f2 = self.register_target(env.file(f2))

            def build(self) -> None:
                self.f1.path.write_text("file 1")
                self.f2.path.write_text("file 2")

        builder = TestBuilder(
            self.env,
            "foo.txt",
            "bar.txt",
        )
        self.execution.build_targets([builder.f1, builder.f2])
        self.assertEqual(
            self.root.joinpath("foo.txt").read_text(),
            "file 1",
        )
        self.assertEqual(
            self.root.joinpath("bar.txt").read_text(),
            "file 2",
        )

    def test_dir_builder(self) -> None:
        """Tests a builder which outputs a directory"""

        class TestBuilder(Builder):
            def __init__(self, env: Environment, d: DirLike):
                super().__init__(env)
                self.target = self.register_target(env.dir(d))

            def build(self) -> None:
                self.target.path.mkdir()
                self.target.path.joinpath("foo.txt").write_text("foo")
                self.target.path.joinpath("bar.txt").write_text("bar")

        builder = TestBuilder(self.env, "foo")
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

        class TestBuilder(SingleFileBuilder):
            def __init__(self, env: Environment, target: File, source: FileLike) -> None:
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
        self.assertFalse(prepared.get_to_build())
        self.assertEqual(prepared.edges[outfile], [infile])

        inpath.write_text("Version 2")
        # Set the mtime to something later. Just using the default system mtimes isn't
        # reliable if the tests run too fast
        os.utime(inpath, (100, 100))
        prepared = self.execution.prepare_build(builder)
        self.assertEqual(prepared.get_to_build(), {outfile})

        self.execution.build_targets(prepared_build=prepared)
        self.assertEqual(outpath.read_text(), "Version 2")


class TestSharedLibrary(Common):
    def test_build_shared_library(self) -> None:
        infile = self.env.file("infile.c")
        infile.path.write_text(
            """
#include <stdio.h>
void main() {
    printf("Hello, world!");
    return;
}
        """
        )
        target = infile.derive("lib", ".so")
        builder = SharedLibrary(self.env, target, infile, CompilerConfig())
        self.execution.build_targets(builder)
        self.assertTrue(target.path.exists())
