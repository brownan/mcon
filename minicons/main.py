import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple, cast

import minicons.execution
from minicons import Dir, Entry, File, Node
from minicons.execution import PreparedBuild


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--construct", default="construct.py")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-B", "--always-make", action="store_true")
    parser.add_argument("--tree", action="store_true")
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

    prepared = current_execution.prepare_build(args["target"])

    if args["tree"]:
        print_tree(prepared)

    if args["always_make"]:
        prepared.to_build = set(prepared.ordered_nodes)

    current_execution.build_targets(prepared_build=prepared, dry_run=args["dry_run"])


def print_tree(
    build: PreparedBuild,
) -> None:
    targets = build.targets
    ordered_nodes = build.ordered_nodes
    edges = build.edges
    out_of_date = build.out_of_date
    to_build = build.to_build
    changed = build.changed

    # First traverse the graph forming a new graph that eliminates non-entry nodes
    new_edges: Dict[Node, List[Node]] = {e: list(d) for e, d in edges.items()}
    for node in ordered_nodes:
        for child in list(new_edges[node]):
            if not isinstance(child, Entry):
                # Remove this edge
                new_edges[node].remove(child)
                # Add new edges to children
                new_edges[node].extend(new_edges[child])

    seen: Dict[Node, int] = {}
    to_visit: List[Tuple[Node, int, bool]] = list((t, 0, False) for t in targets)

    # Nodes are popped off the end of the list. So that we print them in the original order,
    # reverse this list.
    to_visit.reverse()

    print("O = out of date")
    print("B = to build")
    print("C = changed")

    # Now walk this new graph printing out nodes as found, keeping track of the depth.
    while to_visit:
        node, depth, last_child = to_visit.pop()
        assert isinstance(node, Entry)
        skip_children = False

        if depth == 0:
            print()

        print(
            "{} {} {} ".format(
                "O" if node in out_of_date else " ",
                "B" if node in to_build else " ",
                "C" if node in changed else " ",
            ),
            end="",
        )

        if depth == 0:
            print(str(node))
        else:
            print(
                "{}{}\u2500{}".format(
                    "\u2502  " * (depth - 1),
                    "\u251c" if not last_child else "\u2514",
                    node,
                )
            )
        if node in seen:
            skip_children = True
            if new_edges[node]:
                print(
                    "      {}\u2514\u2500(child nodes shown above)".format(
                        "\u2502  " * depth
                    )
                )
        else:
            seen[node] = depth
        if not skip_children:
            children = cast(List[Entry], list(new_edges[node]))
            children_set = set(children)
            # Show directories first, then files. Secondary sort by name
            children.sort(
                key=lambda node: ((Dir, File).index(type(node)), str(node.path)),
                reverse=True,
            )
            for child in children:
                if child in children_set:
                    to_visit.append((child, depth + 1, child is children[0]))
                    children_set.remove(child)


if __name__ == "__main__":
    main()
