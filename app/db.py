from __future__ import annotations

from collections.abc import Iterator
from sqlmodel import Session, SQLModel, create_engine
from app import config

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        config.ensure_dirs()
        _engine = create_engine(
            f"sqlite:///{config.DB_PATH}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def set_engine(engine) -> None:
    """测试用:注入内存引擎。"""
    global _engine
    _engine = engine


def init_db() -> None:
    import app.models  # noqa: F401  确保模型已注册
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
