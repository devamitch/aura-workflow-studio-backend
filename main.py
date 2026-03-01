# backend/main.py — FastAPI backend with DAG detection

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Set
from collections import defaultdict

from .auth import router as auth_router
from .config import get_settings
from .database import Base, engine

settings = get_settings()

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        *(  # dev origins
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ),
        *( [str(settings.frontend_url)] if settings.frontend_url else [] ),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NodePayload(BaseModel):
    id: str
    type: str | None = None
    data: dict | None = None


class EdgePayload(BaseModel):
    id: str
    source: str
    target: str


class PipelinePayload(BaseModel):
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

    # Kahn's algorithm: BFS topological sort
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


@app.get("/")
def read_root():
    return {"Ping": "Pong"}


app.include_router(auth_router)


@app.post("/pipelines/parse")
def parse_pipeline(payload: PipelinePayload) -> ParseResponse:
    num_nodes = len(payload.nodes)
    num_edges = len(payload.edges)
    dag_result = is_dag(payload.nodes, payload.edges)

    return ParseResponse(
        num_nodes=num_nodes,
        num_edges=num_edges,
        is_dag=dag_result,
    )
