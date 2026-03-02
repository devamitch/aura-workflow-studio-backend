from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Pipeline, User, Workspace


router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class GraphPayload(BaseModel):
  nodes: List[dict]
  edges: List[dict]


class PipelineCreate(BaseModel):
  name: str
  description: Optional[str] = None
  graph: GraphPayload


class PipelineUpdate(BaseModel):
  name: Optional[str] = None
  description: Optional[str] = None
  graph: Optional[GraphPayload] = None


class PipelineOut(BaseModel):
  id: int
  name: str
  description: Optional[str]
  graph: GraphPayload
  created_at: datetime
  updated_at: datetime
  node_count: int
  edge_count: int

  model_config = ConfigDict(from_attributes=True)


def _get_or_create_default_workspace(db: Session, user: User) -> Workspace:
  workspace = (
    db.query(Workspace)
    .filter(Workspace.owner_id == user.id)
    .order_by(Workspace.created_at.asc())
    .first()
  )
  if workspace:
    return workspace

  workspace = Workspace(name="Default", owner_id=user.id)
  db.add(workspace)
  db.flush()
  return workspace


def _to_pipeline_out(p: Pipeline) -> PipelineOut:
  graph = p.graph or {"nodes": [], "edges": []}
  nodes = graph.get("nodes") or []
  edges = graph.get("edges") or []
  return PipelineOut(
    id=p.id,
    name=p.name,
    description=p.description,
    graph=GraphPayload(nodes=nodes, edges=edges),
    created_at=p.created_at,
    updated_at=p.updated_at,
    node_count=len(nodes),
    edge_count=len(edges),
  )


@router.get("", response_model=List[PipelineOut])
def list_pipelines(
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
) -> List[PipelineOut]:
  workspace = _get_or_create_default_workspace(db, current_user)
  items = (
    db.query(Pipeline)
    .filter(Pipeline.workspace_id == workspace.id)
    .order_by(Pipeline.created_at.desc())
    .all()
  )
  return [_to_pipeline_out(p) for p in items]


@router.post("", response_model=PipelineOut, status_code=status.HTTP_201_CREATED)
def create_pipeline(
  payload: PipelineCreate,
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
) -> PipelineOut:
  workspace = _get_or_create_default_workspace(db, current_user)
  p = Pipeline(
    workspace_id=workspace.id,
    name=payload.name.strip() or "Untitled",
    description=payload.description,
    graph=payload.graph.model_dump(),
  )
  db.add(p)
  db.flush()
  db.refresh(p)
  return _to_pipeline_out(p)


@router.get("/{pipeline_id}", response_model=PipelineOut)
def get_pipeline(
  pipeline_id: int,
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
) -> PipelineOut:
  p = (
    db.query(Pipeline)
    .join(Workspace, Pipeline.workspace_id == Workspace.id)
    .filter(
      Pipeline.id == pipeline_id,
      Workspace.owner_id == current_user.id,
    )
    .first()
  )
  if not p:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
  return _to_pipeline_out(p)


@router.put("/{pipeline_id}", response_model=PipelineOut)
def update_pipeline(
  pipeline_id: int,
  payload: PipelineUpdate,
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
) -> PipelineOut:
  p = (
    db.query(Pipeline)
    .join(Workspace, Pipeline.workspace_id == Workspace.id)
    .filter(
      Pipeline.id == pipeline_id,
      Workspace.owner_id == current_user.id,
    )
    .first()
  )
  if not p:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")

  if payload.name is not None:
    p.name = payload.name.strip() or p.name
  if payload.description is not None:
    p.description = payload.description
  if payload.graph is not None:
    p.graph = payload.graph.model_dump()

  db.add(p)
  db.flush()
  db.refresh(p)
  return _to_pipeline_out(p)


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pipeline(
  pipeline_id: int,
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
) -> None:
  p = (
    db.query(Pipeline)
    .join(Workspace, Pipeline.workspace_id == Workspace.id)
    .filter(
      Pipeline.id == pipeline_id,
      Workspace.owner_id == current_user.id,
    )
    .first()
  )
  if not p:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")

  db.delete(p)
