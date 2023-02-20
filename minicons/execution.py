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
from minicons.entry import Entry
from minicons.types import Args, SourceLike

logger = getLogger("minicons")


class DependencyError(Exception):
    pass


@dataclasses.dataclass
class PreparedBuild:
    ordered_entries: Sequence["Entry"]
    dependencies: Mapping["Entry", Collection["Entry"]]
    out_of_date: Collection["Entry"]
    to_build: Collection["Entry"]


class Execution:
    """An execution is the top level object which controls the build process

    An execution object keeps track of all the builders, entries, and aliases. Environments
    attached to an Execution will add their builders and entries to their Execution instance.

    Typically, a process will have a single global Execution instance, but for embedding minicons
    in a larger application it may be useful to manage separate Executions.
    """

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).resolve()
        self.aliases: Dict[str, List[Path]] = {}

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

    def _args_to_paths(self, args: Args) -> Iterator[Path]:
        """Resolves a string, path, entry, or builder to Path objects

        Items may also be a list, possibly nested.

        Strings are interpreted as aliases if an alias exists, otherwise it is taken to
        be a path relative to the current working directory.

        """
        list_of_args: List[Args]
        if isinstance(args, (Path, Entry, Builder, str)):
            list_of_args = [args]
        else:
            list_of_args = list(args)

        for arg in list_of_args:
            if isinstance(arg, Entry):
                yield arg.path
            elif isinstance(arg, str):
                if arg in self.aliases:
                    yield from self._args_to_paths(self.aliases[arg])
                else:
                    yield self.root.joinpath(arg)
            elif isinstance(arg, SourceLike):
                yield from self._args_to_paths(arg.target)
            elif isinstance(arg, Path):
                yield arg
            elif isinstance(arg, Iterable):
                # Flatten the list
                yield from self._args_to_paths(arg)
            else:
                raise TypeError(f"Unknown argument type {arg}")

    def register_alias(self, alias: str, entries: Args) -> None:
        paths = list(self._args_to_paths(entries))
        self.aliases[alias] = paths

    def prepare_build(self, targets: Args) -> PreparedBuild:
        """Prepare to build the given targets

        This builds the final dependency graph and the set of out of date nodes
        """
        # Resolve all targets to paths
        target_paths: List[Path] = list(self._args_to_paths(targets))

        # Resolve all paths to Entries
        try:
            target_entries: List["Entry"] = [self.entries[p] for p in target_paths]
        except KeyError as e:
            raise DependencyError(f"Target not found: {e}") from e

        for entry in target_entries:
            entry.built = False

        # Traverse the graph of entry dependencies to get all entries relevant to this build
        # The dependency mapping returned contains not only the explicitly defined
        # entry->entry dependencies in Entry.depends, but also the dependencies
        # implied by the entry's builder's dependencies.
        all_entries, dependencies = _traverse_entry_graph(target_entries)

        # Get the topological ordering of the entries
        ordered_entries = _sort_dag(all_entries, dependencies)

        # Scan all entries to determine which are out of date
        out_of_date_entries: Set["Entry"] = set()
        for entry in ordered_entries:
            if not entry.builder:
                # Leaf nodes are files which don't have a builder and cannot be built.
                # Keep in mind that a file itself cannot be "out of date". A file is
                # only out of date with respect to a its dependencies, and a file
                # in isolation may be used by multiple builders. Since it has no builder
                # itself, we cannot add it to out_of_date_entries because we cannot take any
                # action to make that file "up to date".
                continue
            elif not entry.path.exists():
                # Always build if it doesn't actually exist
                out_of_date_entries.add(entry)
            elif not dependencies[entry]:
                # This entry has no dependencies, meaning there are no explicitly defined
                # dependencies and its builder doesn't have any dependencies.
                # How do we know if this file needs building? In the absence of external
                # information, we don't. In the future we should have a way to specify
                # "always build" on a file or builder, but for now we assume if the file
                # exists, it's good.
                pass
            else:
                # Check if any of its dependencies have changed by comparing the
                # metadata signature to the saved signature
                old_metadata = self._get_metadata(entry.path)
                new_metadata = self._build_entry_metadata(entry, dependencies)
                if old_metadata != new_metadata:
                    out_of_date_entries.add(entry)

        # Build a complete set of all entries that need building: out of date entries plus all
        # dependent entries
        to_build = set(out_of_date_entries)
        for entry in ordered_entries:
            if any(e in to_build for e in dependencies[entry]):
                to_build.add(entry)

        return PreparedBuild(
            ordered_entries=ordered_entries,
            out_of_date=out_of_date_entries,
            to_build=to_build,
            dependencies=dependencies,
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

        ordered_entries = prepared_build.ordered_entries
        out_of_date_entries = prepared_build.out_of_date
        dependencies = prepared_build.dependencies
        to_build = prepared_build.to_build

        if not out_of_date_entries:
            logger.info("All files up to date")
            return

        # Build
        built_entries: Set["Entry"] = set()
        for entry in ordered_entries:
            if entry in to_build and entry not in built_entries:
                # Only entries which have a builder have been added to the out-of-date set
                assert entry.builder

                logger.info("Building %s", entry.builder)
                if not dry_run:
                    self._call_builder(entry.builder)
                    built_entries.update(entry.builder.builds)
                    # Save metadata for this entry
                    for built_entry in entry.builder.builds:
                        new_metadata = self._build_entry_metadata(
                            built_entry, dependencies
                        )
                        self._set_metadata(built_entry.path, new_metadata)

    def _build_entry_metadata(
        self, entry: "Entry", dependencies: Mapping["Entry", Collection["Entry"]]
    ) -> Any:
        # An entry's metadata is used to compare whether it needs to be rebuilt. It encodes
        # the signatures of all entries it depends on.
        dep_metadata: Dict[str, Any] = {}
        for dep in dependencies[entry]:
            dep_metadata[str(dep.path)] = dep.get_metadata()
        return {
            "dependencies": dep_metadata,
        }

    def _call_builder(self, builder: "Builder") -> None:
        """Calls the given builder to build its entries"""
        # First remove its entries and prepare them:
        for entry in builder.builds:
            entry.remove()
        for entry in builder.builds:
            entry.prepare()

        builder.build()

        # check that the outputs were actually created
        for entry in builder.builds:
            if not entry.path.exists():
                raise DependencyError(f"Builder {builder} didn't output {entry}")
            entry.built = True


def _traverse_entry_graph(
    targets: List["Entry"],
) -> Tuple[List["Entry"], Dict["Entry", List["Entry"]]]:
    """Given one or more target entries, traverse the graph of dependencies
    and return all reachable entries, as well as a mapping of dependency relations.

    """
    reachable_entries: List["Entry"] = []
    edges: Dict["Entry", List["Entry"]] = defaultdict(list)

    seen: Set[Entry] = set()
    to_visit = list(targets)
    while to_visit:
        visiting: Entry = to_visit.pop()
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
    nodes: Collection["Entry"], edges_orig: Mapping["Entry", Iterable["Entry"]]
) -> List["Entry"]:
    """Given a set of entries and a mapping describing the edges, returns a topological
    sort starting at the leaf nodes.

    Given edges are dependencies, so the topological sort is actually of the graph with
    all edges reversed. Leaf nodes are nodes with no dependencies.

    """
    # Copy the edges since we'll be mutating it
    edges: Dict["Entry", Set["Entry"]]
    edges = defaultdict(set, ((e, set(deps)) for e, deps in edges_orig.items()))

    # Create the reverse edges, or reverse dependencies (maps dependent nodes onto the
    # set of nodes that depend on it)
    reverse_edges: Dict["Entry", Set["Entry"]] = defaultdict(set)
    for e, deps in edges.items():
        for dep in deps:
            reverse_edges[dep].add(e)

    sorted_nodes: List[Entry] = []
    leaf_nodes: List["Entry"] = [n for n in nodes if not edges.get(n)]

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
