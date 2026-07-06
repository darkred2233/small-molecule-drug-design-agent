from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from medagent.core.config import Settings


def build_engine(settings: Settings):
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if settings.database_url.startswith("sqlite:///./"):
            Path(".local").mkdir(exist_ok=True)
    return create_engine(settings.database_url, connect_args=connect_args)


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=build_engine(settings))


def get_session() -> Generator[Session, None, None]:
    from medagent.api.app import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
