import dataclasses
import json
import sqlite3
from collections import defaultdict
from logging import getLogger
from pathlib import Path
from typing import (
    Any,
    Collection,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from minicons.builder import Builder
from minicons.entry import Entry, Node
from minicons.types import Args

logger = getLogger("minicons")


class DependencyError(Exception):
    pass


@dataclasses.dataclass
class PreparedBuild:
    ordered_nodes: Sequence[Node]
    dependencies: Mapping[Node, Collection[Node]]
    out_of_date: Collection[Entry]
    to_build: Collection[Node]
    metadata: Mapping[Entry, Any]


class Execution:
    """An execution is the top level object which controls the build process

    An execution object keeps track of all the builders, entries, and aliases. Environments
    attached to an Execution will add their builders and entries to their Execution instance.

    Typically, a process will have a single global Execution instance, but for embedding minicons
    in a larger application it may be useful to manage separate Executions.
    """

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).resolve()
        self.aliases: Dict[str, List[Node]] = {}

        # Maps paths to entries. Memoizes calls to file() and dir(), and is used to
        # lookup and resolve target paths given as strings to entries.
        # Path objects are always absolute
        self.entries: Dict[Path, "Entry"] = {}

        self.metadata_db = sqlite3.connect(
            self.root.joinpath(".minicons.sqlite3"), isolation_level=None
        )
        self.metadata_db.execute("""PRAGMA journal_mode=wal""")
        self.metadata_db.execute(
            """
            CREATE TABLE IF NOT EXISTS
            file_metadata (path text PRIMARY KEY, metadata text)
            """
        )

    def _get_metadata(self, path: Path) -> Dict[str, Any]:
        cursor = self.metadata_db.execute(
            """
        SELECT metadata FROM file_metadata WHERE path=?
        """,
            (str(path),),
        )
        row = cursor.fetchone()
        if not row:
            return {}
        return json.loads(row[0])

    def _set_metadata(self, path: Path, metadata: Dict[str, Any]) -> None:
        serialized = json.dumps(metadata)
        self.metadata_db.execute(
            """
            INSERT OR REPLACE INTO file_metadata (path, metadata) VALUES (?, ?)
            """,
            (str(path), serialized),
        )

    def _args_to_nodes(self, args: Args) -> Iterator[Node]:
        """Resolves a string, path, Node, or SourceLike to Node objects

        Items may also be an Iterable, possibly nested.

        Strings are interpreted as aliases if an alias exists, otherwise it is taken to
        be a path relative to the current working directory.

        """
        if isinstance(args, Path):
            yield self.entries[args]
        elif isinstance(args, Node):
            yield args
        elif isinstance(args, str):
            # try interpreting this as an alias first, then as a path
            if args in self.aliases:
                yield from self._args_to_nodes(self.aliases[args])
            else:
                yield self.entries[self.root.joinpath(args)]
        elif hasattr(args, "target"):
            yield from self._args_to_nodes(args.target)
        elif isinstance(args, Iterable):
            for item in args:
                yield from self._args_to_nodes(item)
        else:
            raise TypeError(f"Unknown arg type {args!r}")

    def register_alias(self, alias: str, entries: Args) -> None:
        nodes = list(self._args_to_nodes(entries))
        self.aliases[alias] = nodes

    def prepare_build(self, targets: Args) -> PreparedBuild:
        """Prepare to build the given targets

        This builds the final dependency graph and the set of out of date nodes
        """
        # Resolve all targets to paths
        target_nodes: List[Node] = list(self._args_to_nodes(targets))

        # Traverse the graph of entry dependencies to get all entries relevant to this build
        # The dependency mapping returned contains not only the explicitly defined
        # entry->entry dependencies in Entry.depends, but also the dependencies
        # implied by the entry's builder's dependencies.
        all_nodes, dependencies = _traverse_node_graph(target_nodes)

        # Get the topological ordering of the entries
        ordered_nodes: Sequence[Node] = _sort_dag(all_nodes, dependencies)

        # Maps nodes to other nodes which depend on them
        reverse_dependencies: Dict[Node, Set[Node]] = {}
        for node, deps in dependencies.items():
            for dep in deps:
                reverse_dependencies[dep].add(node)

        # Entry nodes are nodes with a statically defined filesystem path known before
        # calling its builder.
        entry_nodes: Set[Entry] = {node for node in all_nodes if isinstance(node, Entry)}

        # get metadata on all Entry nodes
        metadata: Dict[Entry, Any] = {}
        for node in entry_nodes:
            if node.builder is None and not node.path.exists():
                raise DependencyError(
                    f"Path {node} required but not present on filesystem"
                )
            metadata[node] = node.get_metadata()

        # Gather and compare metadata for entry nodes to see if they are outdated
        # according to all Entries they depend on (anywhere in the ancestry tree)
        outdated: Set[Entry] = set()
        for node in all_nodes:
            if isinstance(node, Entry):
                old_metadata = self._get_metadata(node.path)
                new_metadata = self._build_entry_metadata(
                    node,
                    dependencies,
                    metadata,
                )

                if old_metadata != new_metadata:
                    outdated.add(node)

        # Nodes that are outdated and need rebuilding also imply their descendent nodes should be
        # rebuilt. While such nodes are usually also detected as outdated above, they may
        # not be in the case of an interrupted build where e.g. one dependent node
        # got built but not another. But we don't assume a builder is purely functional,
        # so if a builder runs, we run all descendent builders.
        to_build: Set[Node] = set(outdated)
        for node in ordered_nodes:
            if any(d in to_build for d in dependencies[node]):
                to_build.add(node)

        # Nodes which depend on a non-Entry node require that dependent node to be rebuilt.
        # This is because a non-Entry node's contents are not defined until its builder
        # builds it. For example, a FileSet is used to contain a set of files not known
        # statically. So its builder must build it before it can be used by a downstream
        # dependent builder.
        # Traverse the graph /upward/ so that nodes depending on other nodes propagate
        # correctly. (A FileSet whose builder depends on another FileSet requires
        # both to be built)
        for node in reversed(ordered_nodes):
            if any(d not in entry_nodes for d in dependencies[node]):
                to_build.add(node)

        return PreparedBuild(
            ordered_nodes=ordered_nodes,
            out_of_date=outdated,
            to_build=to_build,
            dependencies=dependencies,
            metadata=metadata,
        )

    def build_targets(
        self,
        targets: Optional[Args] = None,
        prepared_build: Optional[PreparedBuild] = None,
        dry_run: bool = False,
    ) -> None:
        """Build the given targets

        A target or list of targets is given to build. Alternatively, a PreparedBuild as previously
        returned from Execution.prepare_build() may be given.

        """
        if prepared_build is None:
            if targets is None:
                raise ValueError("Either targets or a prepared build must be given")
            else:
                prepared_build = self.prepare_build(targets)
        elif targets is not None:
            raise ValueError("Targets and prepared_build cannot be specified together")

        ordered_nodes = prepared_build.ordered_nodes
        out_of_date_entries = prepared_build.out_of_date
        dependencies = prepared_build.dependencies
        to_build = prepared_build.to_build

        if not out_of_date_entries:
            logger.info("All files up to date")
            return

        # Build
        built_nodes: Set[Node] = set()
        new_metadata: Dict[Entry, Any] = dict(prepared_build.metadata)
        for node in ordered_nodes:
            if node in to_build and node not in built_nodes and node.builder is not None:
                builder = node.builder
                logger.info("Building %s", builder)
                if not dry_run:
                    self._call_builder(builder)
                    built_nodes.update(builder.builds)

                    for built_entry in builder.builds:
                        if isinstance(built_entry, Entry):
                            # Update the metadata dict of each entry's metadata for the newly
                            # built file
                            new_metadata[built_entry] = built_entry.get_metadata()

                            # Now update this entry's cached metadata of all its dependencies
                            self._set_metadata(
                                built_entry.path,
                                self._build_entry_metadata(
                                    built_entry,
                                    dependencies,
                                    new_metadata,
                                ),
                            )

    def _build_entry_metadata(
        self,
        entry: "Entry",
        dependencies: Mapping[Node, Collection[Node]],
        metadata: Mapping[Entry, Any],
    ) -> Dict[str, Any]:
        node_metadata: Dict[str, Any] = {"deps": {}}

        # Simple graph traversal to find all ancestor leaf nodes
        to_visit: List[Node] = list(dependencies[entry])
        while to_visit:
            v = to_visit.pop()
            if v in metadata:
                assert isinstance(v, Entry)
                node_metadata["deps"][str(v.path)] = metadata[v]
            to_visit.extend(dependencies[v])
        return node_metadata

    def _call_builder(self, builder: "Builder") -> None:
        """Calls the given builder to build its entries"""
        # First remove its entries and prepare them:
        for entry in builder.builds:
            if isinstance(entry, Entry):
                entry.remove()
        for entry in builder.builds:
            if isinstance(entry, Entry):
                entry.prepare()

        builder.build()

        # check that the outputs were actually created
        for entry in builder.builds:
            if not entry.path.exists():
                raise DependencyError(f"Builder {builder} didn't output {entry}")


def _traverse_node_graph(
    targets: List["Node"],
) -> Tuple[List["Node"], Dict["Node", List["Node"]]]:
    """Given one or more target nodes, traverse the graph of dependencies
    and return all reachable nodes, as well as a mapping of dependency relations.

    """
    reachable_entries: List["Node"] = []
    edges: Dict["Node", List["Node"]] = defaultdict(list)

    seen: Set[Node] = set()
    to_visit = list(targets)
    while to_visit:
        visiting: Node = to_visit.pop()
        reachable_entries.append(visiting)
        seen.add(visiting)

        dependencies = list(visiting.depends)
        if visiting.builder:
            dependencies.extend(visiting.builder.depends)

        for dep in dependencies:
            edges[visiting].append(dep)
            if dep not in seen:
                to_visit.append(dep)
    return reachable_entries, edges


def _sort_dag(
    nodes: Collection["Node"], edges_orig: Mapping["Node", Iterable["Node"]]
) -> List["Node"]:
    """Given a set of nodes and a mapping describing the edges, returns a topological
    sort starting at the leaf nodes.

    Given edges are dependencies, so the topological sort is actually of the graph with
    all edges reversed. Leaf nodes are nodes with no dependencies.

    """
    # Copy the edges since we'll be mutating it
    edges: Dict["Node", Set["Node"]]
    edges = defaultdict(set, ((e, set(deps)) for e, deps in edges_orig.items()))

    # Create the reverse edges, or reverse dependencies (maps dependent nodes onto the
    # set of nodes that depend on it)
    reverse_edges: Dict["Node", Set["Node"]] = defaultdict(set)
    for e, deps in edges.items():
        for dep in deps:
            reverse_edges[dep].add(e)

    sorted_nodes: List[Node] = []
    leaf_nodes: List[Node] = [n for n in nodes if not edges.get(n)]

    while leaf_nodes:
        node = leaf_nodes.pop()
        sorted_nodes.append(node)
        for m in list(reverse_edges[node]):
            reverse_edges[node].remove(m)
            edges[m].remove(node)
            if not edges[m]:
                leaf_nodes.append(m)

    if any(deps for deps in edges.values()):
        msg = "\n".join(
            f"{n} → {dep}" for n, deps in edges.items() if deps for dep in deps
        )
        raise DependencyError(f"Dependency graph has cycles:\n{msg}")

    return sorted_nodes


def set_current_execution(e: Optional[Execution]) -> None:
    global current_execution
    current_execution = e


def get_current_execution() -> Execution:
    global current_execution
    execution = current_execution
    if not execution:
        raise RuntimeError("No current execution")
    return execution


def register_alias(alias: str, entries: Args) -> None:
    """Registers an alias with the current execution"""
    return get_current_execution().register_alias(alias, entries)


current_execution: Optional[Execution] = None
