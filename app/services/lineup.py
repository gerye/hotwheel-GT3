from __future__ import annotations

from app.config import NUM_LANES


def build_lineup(car_ids: list[int]) -> list[list[int | None]]:
    """返回 4 场 × 4 道的安排;不足 4 辆用 None 补空道。"""
    symbols: list[int | None] = list(car_ids) + [None] * (NUM_LANES - len(car_ids))
    heats: list[list[int | None]] = []
    for h in range(NUM_LANES):
        lane_to_car = [symbols[(l + h) % NUM_LANES] for l in range(NUM_LANES)]
        heats.append(lane_to_car)
    return heats
