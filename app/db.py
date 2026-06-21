from __future__ import annotations

from collections.abc import Iterator
from sqlalchemy import inspect, text
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


def sync_schema(engine) -> None:
    """为已存在的表补齐模型里新增的列(SQLite 的 create_all 不会改已有表)。

    只做"加列"这一种最常见的演进;不处理删列/改类型/改名。
    每条 ALTER 独立 try,失败不阻塞启动。
    """
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # 新表交给 create_all
        existing_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            coltype = col.type.compile(dialect=engine.dialect)
            default_sql = ""
            arg = getattr(col.default, "arg", None)
            if arg is not None and not callable(arg):
                if isinstance(arg, bool):
                    default_sql = f" DEFAULT {1 if arg else 0}"
                elif isinstance(arg, (int, float)):
                    default_sql = f" DEFAULT {arg}"
                else:
                    default_sql = f" DEFAULT '{arg}'"
            ddl = (f'ALTER TABLE "{table.name}" '
                   f'ADD COLUMN {col.name} {coltype}{default_sql}')
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
            except Exception:
                pass  # 列可能已存在或类型不可加,忽略


def init_db() -> None:
    import app.models  # noqa: F401  确保模型已注册
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    sync_schema(engine)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
