from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel
from app.enums import Category, TeamType, SeasonStatus, CarStatus
from app.enums import ProLevel, RaceFormat, RaceStatus


_ALIAS_FIELD = {
    Category.F1: "alias_f1",
    Category.GT3: "alias_gt3",
    Category.ROAD: "alias_road",
}


class Team(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: TeamType
    brand: Optional[str] = None          # 仅厂商车队
    name: str = Field(index=True)        # 宏观名(厂商=品牌+车队;独立=用户名称)
    # 各赛事等级的分队别名(可空)
    alias_f1: Optional[str] = None
    alias_gt3: Optional[str] = None
    alias_road: Optional[str] = None

    def alias_for(self, category: Category) -> str:
        return getattr(self, _ALIAS_FIELD[category]) or ""

    def specific_name(self, category: Category) -> str:
        """分等级的具体名:厂商=品牌+别名+类别+车队;独立=宏观名+别名+类别。"""
        alias = self.alias_for(category)
        if self.type == TeamType.FACTORY:
            return f"{self.brand}{alias}{category.value}车队"
        return f"{self.name}{alias}{category.value}"


class Car(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nickname: str = Field(index=True, unique=True)
    image_path: Optional[str] = None
    casting: str = ""
    brand: str = ""
    category: Category
    description: str = ""
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    status: CarStatus = CarStatus.UNSIGNED
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


class Race(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    category: Category
    pro_level: ProLevel
    format: RaceFormat
    status: RaceStatus = RaceStatus.IN_PROGRESS
    started_at: datetime = Field(default_factory=datetime.utcnow)


class RaceEntry(SQLModel, table=True):
    """报名:单人赛只填 car_id;车队赛 car_id + team_id 都填。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    race_id: int = Field(foreign_key="race.id")
    car_id: int = Field(foreign_key="car.id")
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")


class RaceRound(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    race_id: int = Field(foreign_key="race.id")
    number: int
    is_final: bool = False


class Group(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    round_id: int = Field(foreign_key="raceround.id")
    label: str                      # A/B/C...
    team_a_id: Optional[int] = Field(default=None, foreign_key="team.id")  # 车队赛
    team_b_id: Optional[int] = Field(default=None, foreign_key="team.id")
    mmr_settled: bool = False


class GroupMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    car_id: int = Field(foreign_key="car.id")


class Heat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    number: int                     # 1..4
    recorded: bool = False


class HeatResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    heat_id: int = Field(foreign_key="heat.id")
    car_id: int = Field(foreign_key="car.id")
    lane: int                       # 1..4
    rank: Optional[int] = None      # 1..4;录入后填
    dnf: bool = False


class TieBreak(SQLModel, table=True):
    """并列加赛/1V1 的人工裁决结果。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    winner_car_id: Optional[int] = Field(default=None, foreign_key="car.id")
    winner_car_ids: Optional[str] = Field(default=None)  # 多名额并列:逗号分隔的晋级车 id
    winner_team_id: Optional[int] = Field(default=None, foreign_key="team.id")


class TeamPointEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    team_id: int = Field(foreign_key="team.id")
    points: int
    source_car_id: Optional[int] = Field(default=None, foreign_key="car.id")
    race_id: Optional[int] = Field(default=None, foreign_key="race.id")
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TeamBudget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    team_id: int = Field(foreign_key="team.id")
    budget: int


class CarSalary(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    car_id: int = Field(foreign_key="car.id")
    salary: int
