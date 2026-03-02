from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from config import get_settings
from crypto import encrypt_api_key
from database import get_db
from models import User, UserAPIKey


settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])
keys_router = APIRouter(prefix="/api/v1/keys", tags=["keys"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


class SaveAPIKeyRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider: str
    api_key: str

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"openai", "gemini", "claude"}:
            raise ValueError("Provider must be one of: openai, gemini, claude")
        return normalized

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        if len(value.strip()) < 16:
            raise ValueError("API key appears invalid")
        return value


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expires_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth_header = request.headers.get("Authorization")
    token: str | None = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload: dict | None = None

    # 1) Try first-party Aura token.
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        payload = None

    # 2) Try Supabase JWT token if configured.
    if payload is None and settings.supabase_jwt_secret:
        try:
            payload = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"])
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token and SUPABASE_JWT_SECRET not configured",
        )

    user_id = payload.get("sub")
    if user_id:
        try:
            user = db.query(User).filter(User.id == int(user_id)).first()
            if user:
                return user
        except (TypeError, ValueError):
            pass

    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token payload missing email")

    user = db.query(User).filter(User.email == email).first()
    if user:
        return user

    user = User(
        email=email,
        name=payload.get("user_name") or payload.get("name"),
        avatar_url=payload.get("picture"),
    )
    db.add(user)
    db.flush()
    return user


def _save_api_key_for_user(payload: SaveAPIKeyRequest, db: Session, current_user: User) -> dict:
    encrypted = encrypt_api_key(payload.api_key)
    existing = db.query(UserAPIKey).filter(UserAPIKey.user_id == current_user.id).first()
    if existing:
        existing.encrypted_key = encrypted
        existing.provider = payload.provider
    else:
        db.add(
            UserAPIKey(
                user_id=current_user.id,
                encrypted_key=encrypted,
                provider=payload.provider,
            )
        )
    return {"status": "success", "message": "API key encrypted and saved securely."}


def _api_key_status(db: Session, current_user: User) -> dict:
    existing = db.query(UserAPIKey).filter(UserAPIKey.user_id == current_user.id).first()
    return {
        "has_key": existing is not None,
        "provider": existing.provider if existing else None,
    }


@router.get("/google/login")
async def google_login(request: Request):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )

    return await oauth.google.authorize_redirect(request, settings.google_oauth_redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google auth failed") from exc

    userinfo = token.get("userinfo")
    if not userinfo:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {token['access_token']}"},
            )
            resp.raise_for_status()
            userinfo = resp.json()

    email = userinfo.get("email")
    name = userinfo.get("name")
    picture = userinfo.get("picture")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email not available from Google")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=name, avatar_url=picture)
        db.add(user)
        db.flush()

    access_token = create_access_token({"sub": str(user.id), "email": user.email, "is_admin": user.is_admin})
    frontend_base = settings.frontend_url or "http://localhost:5173"
    return RedirectResponse(url=f"{frontend_base}/?token={access_token}", status_code=status.HTTP_302_FOUND)


@router.get("/me")
def me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    key_info = _api_key_status(db, current_user)
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "is_admin": current_user.is_admin,
        "is_premium": current_user.is_premium,
        "has_api_key": key_info["has_key"],
        "provider": key_info["provider"],
    }


@router.post("/logout")
def logout():
    # JWT is stateless; frontend should delete token/session.
    return {"status": "success"}


@router.post("/api-key")
def save_api_key_legacy(
    payload: SaveAPIKeyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _save_api_key_for_user(payload, db, current_user)


@router.get("/api-key/status")
def get_api_key_status_legacy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _api_key_status(db, current_user)


@keys_router.post("/save")
def save_api_key_v1(
    payload: SaveAPIKeyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _save_api_key_for_user(payload, db, current_user)


@keys_router.get("/status")
def get_api_key_status_v1(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _api_key_status(db, current_user)
