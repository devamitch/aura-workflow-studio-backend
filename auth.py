from datetime import datetime, timedelta
from typing import Optional

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User


settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expires_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_current_user(db: Session = Depends(get_db), request: Request = None) -> User:
    auth_header = request.headers.get("Authorization") if request else None
    token = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id: int | None = payload.get("sub")  # type: ignore[assignment]
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = settings.google_oauth_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google auth failed")

    userinfo = token.get("userinfo")
    if not userinfo:
        async with httpx.AsyncClient() as client:
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

    frontend_base = str(settings.frontend_url) if settings.frontend_url else "http://localhost:5173"
    redirect = RedirectResponse(
        url=f"{frontend_base}/?token={access_token}",
        status_code=status.HTTP_302_FOUND,
    )
    return redirect


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "is_admin": current_user.is_admin,
    }

