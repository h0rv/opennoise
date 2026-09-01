"""Deterministic hierarchy coverage reporting for a multi-parent genre DAG."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class HierarchyError(ValueError):
    """Report invalid hierarchy input instead of inventing a display parent."""


def coverage_report(
    qids: Iterable[str], edges: Iterable[tuple[str, str]], *, focus_qid: str = "Q9778"
) -> dict[str, object]:
    """Return stable roots, multi-parent facts, and focus-subtree coverage.

    Edges are ``(child, parent)``. A root candidate simply has no retained parent in this
    bounded release. It is a navigation entry point, not a claim that it is the sole or
    universal parent for any genre.
    """
    nodes = tuple(sorted(set(qids)))
    node_set = set(nodes)
    parents: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    normalized_edges = tuple(sorted(set(edges)))
    for child, parent in normalized_edges:
        if child == parent or child not in node_set or parent not in node_set:
            raise HierarchyError("hierarchy edges must join two distinct declared QIDs")
        parents[child].add(parent)
        children[parent].add(child)
    _assert_acyclic(nodes, children)
    roots = tuple(qid for qid in nodes if not parents[qid])
    root_candidates = tuple(
        {"qid": qid, "direct_children": len(children[qid])}
        for qid in sorted(roots, key=lambda item: (-len(children[item]), item))
    )
    multiple_parents = tuple(
        {"qid": qid, "parent_qids": tuple(sorted(parents[qid]))}
        for qid in nodes
        if len(parents[qid]) > 1
    )
    focus_nodes = _descendants(focus_qid, children) if focus_qid in node_set else frozenset()
    focus_edges = sum(
        1 for child, parent in normalized_edges if child in focus_nodes and parent in focus_nodes
    )
    return {
        "schema_version": 1,
        "node_count": len(nodes),
        "direct_edge_count": len(normalized_edges),
        "root_candidates": root_candidates,
        "multi_parent_nodes": multiple_parents,
        "focus": {
            "qid": focus_qid,
            "present": bool(focus_nodes),
            "closure_node_count": len(focus_nodes),
            "closure_direct_edge_count": focus_edges,
        },
        "display_parent_policy": "not_selected; preserve every exact direct Wikidata parent",
    }


def _descendants(root: str, children: dict[str, set[str]]) -> frozenset[str]:
    seen = {root}
    pending = [root]
    while pending:
        node = pending.pop()
        for child in sorted(children[node]):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return frozenset(seen)


def _assert_acyclic(nodes: tuple[str, ...], children: dict[str, set[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise HierarchyError("hierarchy must be acyclic")
        if node in visited:
            return
        visiting.add(node)
        for child in sorted(children[node]):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in nodes:
        visit(node)
