"""
Drain — lightweight log template mining algorithm.

A prefix-tree based approach that groups log messages by length and
leading tokens, then merges them into templates by replacing variable
positions with wildcards.

Reference: He et al., "Drain: An Online Log Parsing Approach with Fixed
Depth Tree" (ICWS 2017).

This is a custom implementation (no external dependency) optimized for
the Netscope ingest hot path.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class LogCluster:
    """A cluster of similar log messages sharing one template."""
    template_tokens: list[str]
    count: int = 0
    sample: str = ""

    @property
    def template(self) -> str:
        return " ".join(self.template_tokens)

    @property
    def cluster_id(self) -> str:
        """Deterministic ID from template content (SHA-1 prefix 12 chars)."""
        return hashlib.sha1(self.template.encode()).hexdigest()[:12]


class _Node:
    """Internal prefix-tree node."""
    __slots__ = ("children", "clusters")

    def __init__(self):
        self.children: dict[str, _Node] = {}
        self.clusters: list[LogCluster] = []


class DrainTree:
    """
    Drain prefix tree for online log template mining.

    Parameters:
        depth: Number of prefix tokens to use for tree traversal (default 4).
        sim_threshold: Minimum similarity (0.0~1.0) to merge into existing
                       cluster (default 0.4).
        max_clusters: Maximum number of clusters to prevent memory blowup
                      (default 10_000).
    """

    def __init__(
        self,
        depth: int = 4,
        sim_threshold: float = 0.4,
        max_clusters: int = 10_000,
    ):
        self.depth = depth
        self.sim_threshold = sim_threshold
        self.max_clusters = max_clusters
        self._root: dict[int, _Node] = {}  # length -> root node
        self._cluster_count = 0

    def add(self, masked_message: str) -> LogCluster:
        """
        Process a single masked log message, returning the cluster it
        was assigned to (existing or newly created).
        """
        tokens = masked_message.split()
        length = len(tokens)

        if length == 0:
            tokens = ["<EMPTY>"]
            length = 1

        # Navigate prefix tree
        if length not in self._root:
            self._root[length] = _Node()

        node = self._root[length]
        for i in range(min(self.depth, length)):
            token = tokens[i]
            if token.startswith("<") and token.endswith(">"):
                token = "<*>"  # wildcard group
            if token not in node.children:
                node.children[token] = _Node()
            node = node.children[token]

        # Find best matching cluster at leaf
        best_cluster = None
        best_sim = 0.0

        for cluster in node.clusters:
            sim = self._similarity(tokens, cluster.template_tokens)
            if sim > best_sim:
                best_sim = sim
                best_cluster = cluster

        if best_cluster and best_sim >= self.sim_threshold:
            # Merge into existing cluster
            best_cluster.template_tokens = self._merge_tokens(
                best_cluster.template_tokens, tokens
            )
            best_cluster.count += 1
            return best_cluster

        # Create new cluster
        if self._cluster_count >= self.max_clusters:
            # Evict least-used cluster from this node
            if node.clusters:
                node.clusters.sort(key=lambda c: c.count)
                evicted = node.clusters.pop(0)
                self._cluster_count -= 1

        new_cluster = LogCluster(
            template_tokens=list(tokens),
            count=1,
            sample=masked_message,
        )
        node.clusters.append(new_cluster)
        self._cluster_count += 1
        return new_cluster

    def all_clusters(self) -> list[LogCluster]:
        """Return all clusters in the tree."""
        result: list[LogCluster] = []
        self._collect(self._root, result)
        return result

    def _collect(self, nodes, result):
        if isinstance(nodes, dict):
            for node in nodes.values():
                self._collect(node, result)
        elif isinstance(nodes, _Node):
            result.extend(nodes.clusters)
            for child in nodes.children.values():
                self._collect(child, result)

    @staticmethod
    def _similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
        """Token-level similarity: fraction of positions that match."""
        if len(tokens_a) != len(tokens_b):
            return 0.0
        if not tokens_a:
            return 1.0
        matches = sum(
            1 for a, b in zip(tokens_a, tokens_b)
            if a == b
        )
        return matches / len(tokens_a)

    @staticmethod
    def _merge_tokens(
        template: list[str], new_tokens: list[str]
    ) -> list[str]:
        """Merge two token sequences, replacing mismatched positions with <*>."""
        return [
            t if t == n else "<*>"
            for t, n in zip(template, new_tokens)
        ]
