import pytest
from app.services import grouping as g


def test_sizes_16():
    assert g.group_sizes(16) == [4, 4, 4, 4]


def test_sizes_14():
    assert g.group_sizes(14) == [4, 4, 3, 3]


def test_sizes_10():
    assert g.group_sizes(10) == [4, 3, 3]


def test_sizes_6():
    assert g.group_sizes(6) == [3, 3]


def test_sizes_7():
    assert g.group_sizes(7) == [4, 3]


def test_sizes_3_and_4():
    assert g.group_sizes(3) == [3]
    assert g.group_sizes(4) == [4]


def test_invalid_counts():
    for n in (0, 1, 2, 5):
        with pytest.raises(g.GroupingError):
            g.group_sizes(n)


def test_partition_assigns_all_and_labels(deterministic):
    cars = list(range(1, 11))  # 10 辆
    groups = g.partition(cars, seed=42)
    assert [len(m) for m in [grp.members for grp in groups]] == [4, 3, 3]
    assert {c for grp in groups for c in grp.members} == set(cars)
    assert [grp.label for grp in groups] == ["A", "B", "C"]


def test_partition_is_random_with_seed():
    cars = list(range(1, 7))
    a = g.partition(cars, seed=1)
    b = g.partition(cars, seed=1)
    assert [grp.members for grp in a] == [grp.members for grp in b]
