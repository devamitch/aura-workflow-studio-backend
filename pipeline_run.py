from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai.chat import chat_service
from auth import get_current_user
from crypto import decrypt_api_key
from database import get_db
from models import User, UserAPIKey
from schemas import PipelinePayload, is_dag


router = APIRouter(prefix="/pipelines", tags=["pipelines-run"])


class PipelineRunRequest(BaseModel):
    graph: PipelinePayload
    inputs: Dict[str, Any] = Field(default_factory=dict)


class PipelineRunResult(BaseModel):
    outputs: Dict[str, Any]


def _get_provider_and_api_key(db: Session, user: User) -> Tuple[str, str]:
    user_key = db.query(UserAPIKey).filter(UserAPIKey.user_id == user.id).first()
    if not user_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No API key configured. Save your provider key to run workflows.",
        )
    return user_key.provider, decrypt_api_key(user_key.encrypted_key)


def _toposort(nodes: List[Any], edges: List[Any]) -> List[str]:
    node_ids: Set[str] = {n.id for n in nodes}
    if not is_dag(nodes, edges):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pipeline contains cycles; cannot execute.",
        )

    adj: Dict[str, List[str]] = defaultdict(list)
    indeg: Dict[str, int] = {nid: 0 for nid in node_ids}
    for e in edges:
        if e.source in node_ids and e.target in node_ids:
            adj[e.source].append(e.target)
            indeg[e.target] = indeg.get(e.target, 0) + 1

    q: deque[str] = deque([nid for nid, deg in indeg.items() if deg == 0])
    order: List[str] = []
    while q:
        cur = q.popleft()
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    return order


@router.post("/run", response_model=PipelineRunResult)
def run_pipeline(
    payload: PipelineRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PipelineRunResult:
    provider, api_key = _get_provider_and_api_key(db, current_user)
    nodes = payload.graph.nodes
    edges = payload.graph.edges

    if not nodes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty pipeline")

    order = _toposort(nodes, edges)
    by_id: Dict[str, Any] = {n.id: n for n in nodes}
    values: Dict[str, Any] = {}

    def incoming(node_id: str) -> List[Any]:
        src_ids = [e.source for e in edges if e.target == node_id]
        return [values[s] for s in src_ids if s in values]

    for nid in order:
        node = by_id[nid]
        ntype = (node.type or "").lower()
        data = node.data or {}

        if ntype == "custominput":
            name = data.get("inputName") or nid
            values[nid] = payload.inputs.get(name)

        elif ntype == "text":
            values[nid] = data.get("text") or ""

        elif ntype == "llm":
            parts = incoming(nid)
            system = "You are Aura, an AI assistant."
            prompt = "\n\n".join(str(p) for p in parts if p is not None)
            try:
                answer = chat_service.chat(
                    system,
                    [("user", prompt or "Describe this workflow briefly.")],
                    provider=provider,
                    api_key=api_key,
                )
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            values[nid] = answer

        elif ntype == "customoutput":
            vals = incoming(nid)
            values[nid] = vals[-1] if vals else None

        else:
            vals = incoming(nid)
            values[nid] = vals[-1] if len(vals) == 1 else vals

    outputs: Dict[str, Any] = {}
    for nid, node in by_id.items():
        if (node.type or "").lower() == "customoutput":
            name = (node.data or {}).get("outputName") or nid
            outputs[name] = values.get(nid)

    if not outputs:
        outputs["result"] = values.get(order[-1])

    return PipelineRunResult(outputs=outputs)
