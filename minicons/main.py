import argparse
import logging

import minicons
from minicons import Execution


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("sconstruct")
    parser.add_argument("target", nargs="+")
    args = vars(parser.parse_args())

    contents = open(args["sconstruct"], "r").read()
    code = compile(contents, args["sconstruct"], "exec", optimize=0)

    current_execution = Execution()
    minicons.set_current_execution(current_execution)
    try:
        exec(code, {})
    finally:
        minicons.set_current_execution(None)

    current_execution.build_targets(args["target"])


if __name__ == "__main__":
    main()
