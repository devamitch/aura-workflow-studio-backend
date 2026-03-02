from __future__ import annotations

from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ai.chat import chat_service
from ai.embeddings import embedding_service
from auth import get_current_user
from crypto import decrypt_api_key
from database import get_db
from models import Document, DocumentChunk, User, UserAPIKey, Workspace


router = APIRouter(prefix="/rag", tags=["rag"])


class DocumentCreate(BaseModel):
    name: str
    text: str


class DocumentOut(BaseModel):
    id: int
    name: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class RAGQuery(BaseModel):
    query: str
    top_k: int = 5


class RAGAnswer(BaseModel):
    answer: str
    sources: List[int]


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


def _get_provider_and_api_key(db: Session, user: User) -> Tuple[str, str]:
    user_key = db.query(UserAPIKey).filter(UserAPIKey.user_id == user.id).first()
    if not user_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No API key configured. Save your provider key to continue.",
        )
    return user_key.provider, decrypt_api_key(user_key.encrypted_key)


def _chunk_text(text: str, max_chars: int = 800) -> List[str]:
    text = text.strip()
    if not text:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        window = text[start:end]
        dot = window.rfind(". ")
        if dot != -1 and end != len(text):
            end = start + dot + 2
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentOut:
    provider, api_key = _get_provider_and_api_key(db, current_user)
    workspace = _get_or_create_default_workspace(db, current_user)

    doc = Document(
        workspace_id=workspace.id,
        name=payload.name.strip() or "Untitled",
        source_type="text",
    )
    db.add(doc)
    db.flush()

    chunks = _chunk_text(payload.text)
    try:
        for idx, chunk in enumerate(chunks):
            embedding = embedding_service.embed_text(chunk, provider=provider, api_key=api_key)
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    text=chunk,
                    embedding=embedding,
                )
            )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.flush()
    db.refresh(doc)
    return DocumentOut(id=doc.id, name=doc.name, created_at=doc.created_at.isoformat())


@router.get("/documents", response_model=List[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[DocumentOut]:
    workspace = _get_or_create_default_workspace(db, current_user)
    docs = (
        db.query(Document)
        .filter(Document.workspace_id == workspace.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [DocumentOut(id=d.id, name=d.name, created_at=d.created_at.isoformat()) for d in docs]


@router.post("/query", response_model=RAGAnswer)
def query_rag(
    payload: RAGQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RAGAnswer:
    provider, api_key = _get_provider_and_api_key(db, current_user)
    workspace = _get_or_create_default_workspace(db, current_user)

    all_chunks = (
        db.query(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(Document.workspace_id == workspace.id)
        .all()
    )
    if not all_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No documents have been added yet.",
        )

    try:
        query_embedding = embedding_service.embed_text(payload.query, provider=provider, api_key=api_key)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    scored: List[tuple[float, DocumentChunk]] = []
    for chunk in all_chunks:
        emb = chunk.embedding or []
        score = _cosine_similarity(query_embedding, emb)
        scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = [c for _, c in scored[: max(1, payload.top_k)]]

    context_text = "\n\n".join(f"[Doc {c.document_id}] {c.text}" for c in top)
    system_prompt = (
        "You are Aura, an AI research assistant. "
        "Answer the user's question using only the provided context. "
        "If the context is insufficient, say so clearly."
    )
    user_message = f"Context:\n{context_text}\n\nQuestion: {payload.query}"

    try:
        answer = chat_service.chat(
            system_prompt,
            [("user", user_message)],
            provider=provider,
            api_key=api_key,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    source_ids = sorted({c.document_id for c in top})
    return RAGAnswer(answer=answer, sources=source_ids)
