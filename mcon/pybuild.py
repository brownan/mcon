"""Routines for integrating this tool as a backend for a PEP 517 build frontend"""
from pathlib import Path
from typing import Any, Optional

from mcon import File
from mcon.execution import Execution
from mcon.main import execute_construct


def _get_construct_path() -> Path:
    p = Path.cwd() / "construct.py"
    if not p.is_file():
        raise RuntimeError("Could not find construct.py in current directory")
    return p


def _exec_target(target: str, **kwargs: Any) -> str:
    construct_path = _get_construct_path()
    root = construct_path.parent
    execution = Execution(root)
    execution.update(kwargs)
    execute_construct(
        construct_path,
        execution,
    )
    execution.build_targets(targets=target)
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
    return _exec_target("wheel", WHEEL_DIST_DIR=wheel_directory)


def build_sdist(
    sdist_directory: str,
    config_settings: Optional[dict] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    return _exec_target("sdist", SDIST_DIST_DIR=sdist_directory)


def build_editable(
    wheel_directory: str,
    config_settings: Optional[dict] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    return _exec_target("editable", EDITABLE_DIST_DIR=wheel_directory)
