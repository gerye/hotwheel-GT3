from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


class GroupingError(Exception):
    pass


@dataclass
class PlannedGroup:
    label: str
    members: list[int] = field(default_factory=list)


def group_sizes(n: int) -> list[int]:
    """把 n 拆成若干 3-4 的组,优先 4 辆组。"""
    if n < 3 or n == 5:
        raise GroupingError(f"{n} 辆车无法满足「每组 3-4 辆」,请调整参赛数量")
    groups = math.ceil(n / 4)
    if 3 * groups > n:                 # 理论上仅 n==5 触发,已被上面拦截
        raise GroupingError(f"{n} 辆车无法分组")
    fours = n - 3 * groups            # 4 辆组数量
    threes = groups - fours           # 3 辆组数量
    return [4] * fours + [3] * threes


def _labels(k: int) -> list[str]:
    return [chr(ord("A") + i) for i in range(k)]


def partition(car_ids: list[int], seed: int | None = None) -> list[PlannedGroup]:
    sizes = group_sizes(len(car_ids))
    pool = list(car_ids)
    rng = random.Random(seed)
    rng.shuffle(pool)
    result: list[PlannedGroup] = []
    idx = 0
    for label, size in zip(_labels(len(sizes)), sizes):
        result.append(PlannedGroup(label=label, members=pool[idx:idx + size]))
        idx += size
    return result
