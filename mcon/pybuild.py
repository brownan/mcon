"""Routines for integrating this tool as a backend for a PEP 517 build frontend"""
from pathlib import Path
from typing import Optional

from mcon import File
from mcon.execution import Execution
from mcon.main import execute_construct


def _get_construct_path() -> Path:
    p = Path.cwd() / "construct.py"
    if not p.is_file():
        raise RuntimeError("Could not find construct.py in current directory")
    return p


def _exec_target(target: str, build_dir: str) -> str:
    construct_path = _get_construct_path()
    root = construct_path.parent
    execution = Execution(root)
    execution["WHEEL_BUILD_DIR"] = build_dir
    execute_construct(
        construct_path,
        execution,
        [target],
    )
    targets = execution.aliases[target]
    if len(targets) != 1:
        raise RuntimeError("Target 'wheel' had more than one target")
    node = targets[0]
    assert isinstance(node, File)
    return str(node.path)


def build_wheel(
    wheel_directory: str,
    config_settings: Optional[dict] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    return _exec_target("wheel", wheel_directory)


def build_sdist(
    sdist_directory: str,
    config_settings: Optional[dict] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    return _exec_target("sdist", sdist_directory)


def build_editable(
    wheel_directory: str,
    config_settings: Optional[dict] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    return _exec_target("editable", wheel_directory)
