import argparse
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from mcon import Dir, Entry, File, FileSet, Node
from mcon.execution import Execution, PreparedBuild, set_current_execution

logger = logging.getLogger("mcon")


class TreeAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Union[str, Sequence[Any], None],
        option_string: Optional[str] = None,
    ) -> None:
        if option_string and option_string.endswith("=all"):
            namespace.tree = "all"
        else:
            namespace.tree = True


log_format = "%(log_color)s%(levelname)-8s%(reset)s %(message)s"


def esc(*codes: int) -> str:
    return "\033[{}m".format(";".join(str(code) for code in codes))


LOG_COLORS = {
    logging.DEBUG: esc(36),
    logging.INFO: esc(37),
    logging.WARNING: esc(33),
    logging.ERROR: esc(31),
    logging.CRITICAL: esc(37, 41),
}
RESET = esc(0)


class ColorFormatter(logging.Formatter):
    def formatMessage(self, record: logging.LogRecord) -> str:
        record.log_color = LOG_COLORS.get(record.levelno, "")
        record.reset = RESET
        return super().formatMessage(record)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--construct", default="construct.py")
    parser.add_argument("-B", "--always-build", action="store_true")
    parser.add_argument("-j", "--parallel", type=int, default=os.cpu_count())
    parser.add_argument("-d", "--dry-run", action="store_true")
    parser.add_argument("--tree", "--tree=all", action=TreeAction, nargs=0)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("-q", "--quiet", action="count", default=0)
    parser.add_argument("target", nargs="+")
    args = vars(parser.parse_args())

    level = logging.INFO
    level -= 10 * args["verbose"]
    level += 10 * args["quiet"]
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(log_format))
    root.addHandler(handler)

    construct_path = Path(args["construct"]).resolve()
    execution = Execution(construct_path.parent)
    execution.update(os.environ)
    execute_construct(
        construct_path,
        execution,
    )

    prepared = execution.prepare_build(args["target"])

    if args["always_build"]:
        prepared.out_of_date = prepared.buildable_entries

    if args["tree"]:
        print_tree(prepared, all_nodes=args["tree"] == "all")

    execution.build_targets(
        prepared_build=prepared, dry_run=args["dry_run"], parallel=args["parallel"]
    )


def execute_construct(
    construct_path: Path,
    execution: Execution,
) -> None:
    contents = open(construct_path, "r").read()
    code = compile(contents, construct_path.name, "exec", optimize=0)

    set_current_execution(execution)
    try:
        exec(code, {})
    finally:
        set_current_execution(None)


def print_tree(
    build: PreparedBuild,
    all_nodes: bool = False,
) -> None:
    targets = build.targets
    ordered_nodes = build.ordered_nodes
    edges = build.edges
    out_of_date = build.out_of_date
    to_build = build.get_to_build()
    changed = build.changed

    new_edges: Dict[Node, List[Node]] = {e: list(d) for e, d in edges.items()}

    # Traverse the nodes and modify the tree for more useful output
    for node in ordered_nodes:
        for child in list(new_edges[node]):
            # Eliminate non-entry nodes. i.e. only show File and Directory nodes in the
            # tree output. Leaving in other nodes may be handy for debugging the dependency
            # calculation logic.
            if not isinstance(child, Entry):
                # Remove this edge
                new_edges[node].remove(child)
                # Add new edges to children
                new_edges[node].extend(new_edges[child])

            # Cut off all parts of the tree that aren't being built, unless the full tree
            # is requested
            elif (
                not all_nodes
                and child not in to_build
                and child not in changed
                and child not in out_of_date
            ):
                new_edges[node].remove(child)

    seen: Set[Node] = set()
    to_visit: List[Tuple[Node, List[bool], bool]] = list((t, [], False) for t in targets)

    # Nodes are popped off the end of the list. So that we print them in the original order,
    # reverse this list.
    to_visit.reverse()

    print("C = changed")
    print("O = out of date")
    print("B = to build")

    # Now walk this new graph printing out nodes as found, keeping track of the depth.
    while to_visit:
        node, depth_seq, last_child = to_visit.pop()
        skip_children = bool(node in seen and new_edges[node])

        if not depth_seq:
            print()

        _print_line(
            node in out_of_date,
            node in to_build,
            node in changed,
            depth_seq,
            last_child,
            str(node),
            skip_children,
        )

        if not skip_children:
            seen.add(node)
            children = list(new_edges[node])
            children_set = set(children)

            # Show directories first, then files. Secondary sort by name
            children.sort(
                key=lambda node: ((FileSet, Dir, File).index(type(node)), str(node)),
                reverse=True,
            )
            for child in children:
                if child in children_set:
                    if not depth_seq:
                        new_depth_seq = [True]
                    else:
                        new_depth_seq = depth_seq[:-1] + [not last_child, True]
                    to_visit.append((child, new_depth_seq, child is children[0]))
                    children_set.remove(child)


def _print_line(
    out_of_date: bool,
    to_build: bool,
    changed: bool,
    depth_seq: List[bool],
    last_child: bool,
    name: str,
    omit_children: bool,
) -> None:
    parts = []
    parts.append(
        "{} {} {} ".format(
            "C" if changed else " ",
            "O" if out_of_date else " ",
            "B" if to_build else " ",
        )
    )

    if depth_seq:
        parts.append(" ")
        for d in depth_seq[:-1]:
            if d:
                parts.append("│  ")
            else:
                parts.append("   ")

        if last_child:
            parts.append("└─")
        else:
            parts.append("├─")

    parts.append(name)

    print("".join(parts))
    if omit_children:
        if last_child:
            new_depth_seq = depth_seq[:-1] + [False, True]
        else:
            new_depth_seq = depth_seq + [True]
        _print_line(
            False,
            False,
            False,
            new_depth_seq,
            True,
            "(child nodes shown above)",
            False,
        )


if __name__ == "__main__":
    main()
