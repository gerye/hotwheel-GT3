from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel
from app.enums import Category, TeamType, SeasonStatus


class Team(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: TeamType
    brand: Optional[str] = None          # 仅厂商车队
    name: str = Field(index=True)        # 显示名(厂商=品牌+车队;独立=用户名称)


class Car(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nickname: str = Field(index=True, unique=True)
    image_path: Optional[str] = None
    casting: str = ""
    brand: str = ""
    category: Category
    description: str = ""
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    season_mmr: float = 1500.0
    historical_mmr: float = 1500.0


class Season(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    status: SeasonStatus = SeasonStatus.ACTIVE
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None


class CarSeasonMMR(SQLModel, table=True):
    """赛季结束时为每辆车保存的 MMR 快照。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    car_id: int = Field(foreign_key="car.id")
    mmr: float
