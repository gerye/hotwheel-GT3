from __future__ import annotations

from sqlalchemy import inspect, text
from sqlmodel import create_engine
from sqlmodel.pool import StaticPool
from app import db


def test_sync_schema_adds_missing_column():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    # 模拟旧版本:建一个缺 mmr_settled 列的 group 表
    with eng.begin() as conn:
        conn.execute(text(
            'CREATE TABLE "group" (id INTEGER PRIMARY KEY, round_id INTEGER, '
            'label VARCHAR, team_a_id INTEGER, team_b_id INTEGER)'))
        conn.execute(text(
            'INSERT INTO "group" (round_id, label) VALUES (1, \'A\')'))

    db.set_engine(eng)
    try:
        db.init_db()  # create_all 建其余表 + sync_schema 补列
        cols = {c["name"] for c in inspect(eng).get_columns("group")}
        assert "mmr_settled" in cols
        # 旧行也能读出,默认 0/False
        with eng.connect() as conn:
            val = conn.execute(text(
                'SELECT mmr_settled FROM "group" WHERE label=\'A\'')).scalar()
        assert val in (0, False)
    finally:
        db.set_engine(None)
