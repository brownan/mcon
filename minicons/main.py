import argparse
import logging
from pathlib import Path

import minicons.execution


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--construct", default="construct.py")
    parser.add_argument("target", nargs="+")
    args = vars(parser.parse_args())

    construct_path = Path(args["construct"]).resolve()
    contents = open(construct_path, "r").read()
    code = compile(contents, args["construct"], "exec", optimize=0)

    current_execution = minicons.execution.Execution(construct_path.parent)
    minicons.execution.set_current_execution(current_execution)
    try:
        exec(code, {})
    finally:
        minicons.execution.set_current_execution(None)

    current_execution.build_targets(args["target"])


if __name__ == "__main__":
    main()
