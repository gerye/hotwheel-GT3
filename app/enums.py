from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    F1 = "F1"
    GT3 = "GT3"
    ROAD = "公路车"


class CarStatus(str, Enum):
    UNSIGNED = "未签约"
    ACTIVE = "现役"
    RETIRED = "退役"


class TeamType(str, Enum):
    FACTORY = "厂商车队"
    INDEPENDENT = "独立车队"


class ProLevel(str, Enum):
    PRO = "专业"
    EXHIBITION = "表演"


class RaceFormat(str, Enum):
    SOLO = "单人锦标赛"
    TEAM = "车队锦标赛"


class RaceStatus(str, Enum):
    IN_PROGRESS = "进行中"
    FINISHED = "已结束"


class SeasonStatus(str, Enum):
    ACTIVE = "进行中"
    FINISHED = "已结束"


class ContractType(str, Enum):
    LONG = "长期"
    SHORT = "短期"
