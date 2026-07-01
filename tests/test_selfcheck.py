from __future__ import annotations

import pytest

from scripts.sim_selfcheck import run


@pytest.mark.slow
def test_full_chain_selfcheck_has_no_problems():
    """守护 scripts/sim_selfcheck 这个工具不退化:全链路模拟应零问题。"""
    problems = run(seed=20260626)
    assert problems == [], "全链路自检发现问题:\n" + "\n".join(problems)
