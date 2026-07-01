from __future__ import annotations

import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool
from app import db


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False,
                     help="同时运行标记 slow 的慢速集成测试(如全链路自检)")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 慢速集成测试;默认跳过,加 --runslow 运行")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="慢速测试,默认跳过(加 --runslow 运行)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models  # noqa: F401
    SQLModel.metadata.create_all(eng)
    db.set_engine(eng)
    yield eng
    db.set_engine(None)


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def deterministic():
    import random
    random.seed(0)
    yield
