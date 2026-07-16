from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from medagent.core.config import Settings, get_settings


_session_factory: sessionmaker[Session] | None = None


def build_engine(settings: Settings):
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if settings.database_url.startswith("sqlite:///./"):
            Path(".local").mkdir(exist_ok=True)
    return create_engine(settings.database_url, connect_args=connect_args)


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=build_engine(settings))


def configure_session_factory(session_factory: sessionmaker[Session]) -> None:
    global _session_factory
    _session_factory = session_factory


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = build_session_factory(get_settings())
    return _session_factory


def get_session() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    yield from get_session()
