from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import get_settings


settings = get_settings()

if not settings.database_url:
    raise RuntimeError(
        "DATABASE_URL is not configured. "
        "Set it to a Postgres or Supabase connection string before running the Aura backend."
    )

engine = create_engine(settings.database_url, echo=False, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

