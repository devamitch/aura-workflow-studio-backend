from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set

from pydantic import BaseModel, ConfigDict


class NodePayload(BaseModel):
    id: str
    type: str | None = None
    data: dict | None = None


class EdgePayload(BaseModel):
    id: str
    source: str
    target: str


class PipelinePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nodes: List[NodePayload]
    edges: List[EdgePayload]


class ParseResponse(BaseModel):
    num_nodes: int
    num_edges: int
    is_dag: bool


def is_dag(nodes: List[NodePayload], edges: List[EdgePayload]) -> bool:
    """Check if the graph formed by nodes and edges is a DAG using Kahn's algorithm."""
    node_ids: Set[str] = {n.id for n in nodes}
    adj: Dict[str, List[str]] = defaultdict(list)
    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in edges:
        if edge.source in node_ids and edge.target in node_ids:
            adj[edge.source].append(edge.target)
            in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    visited_count = 0

    while queue:
        current = queue.pop(0)
        visited_count += 1
        for neighbor in adj[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return visited_count == len(node_ids)
