from app.services import lineup as L


def test_four_cars_each_lane_once():
    cars = [10, 20, 30, 40]
    heats = L.build_lineup(cars)         # list[list[car_or_None]]，外层=场(4),内层=道(4)
    assert len(heats) == 4
    for h in heats:
        assert len(h) == 4
    # 每辆车在 4 场里把 4 个道各跑一次
    for car in cars:
        lanes = []
        for h in heats:
            lanes.append(h.index(car))
        assert sorted(lanes) == [0, 1, 2, 3]
    # 每辆车每场都出赛
    for h in heats:
        assert set(c for c in h if c is not None) == set(cars)


def test_three_cars_run_four_heats_and_have_empty_lane():
    cars = [10, 20, 30]
    heats = L.build_lineup(cars)
    assert len(heats) == 4
    for car in cars:
        # 每车每场都出赛
        assert sum(1 for h in heats if car in h) == 4
        # 4 场里访问 4 个不同道(其中含拉丁方分配)
        lanes = [h.index(car) for h in heats]
        assert sorted(lanes) == [0, 1, 2, 3]
    # 每场恰有一个空道
    for h in heats:
        assert h.count(None) == 1
