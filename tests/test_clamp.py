"""스탯 클램프 — 모델이 과한 숫자를 내도 게임에 그대로 들어가지 않는지 확인."""

from __future__ import annotations

import math

from app.forge.clamp import clamp_stats
from app.forge.schema import STAT_BUDGET, STAT_KEYS, STAT_RANGES, ForgeStats


def normalized_total(stats: ForgeStats) -> float:
    values = stats.model_dump()
    return sum(
        (values[key] - STAT_RANGES[key].min)
        / (STAT_RANGES[key].max - STAT_RANGES[key].min)
        for key in STAT_KEYS
    )


def test_values_are_pulled_into_range():
    stats, report = clamp_stats(
        ForgeStats(damage=9999, shotsPerSecond=-5, projectileSpeed=0, lifetime=100)
    )

    for key in STAT_KEYS:
        value = stats.model_dump()[key]
        assert STAT_RANGES[key].min <= value <= STAT_RANGES[key].max
    assert set(report.clamped) == set(STAT_KEYS)


def test_all_max_is_scaled_down_to_budget():
    maxed = ForgeStats(
        damage=STAT_RANGES["damage"].max,
        shotsPerSecond=STAT_RANGES["shotsPerSecond"].max,
        projectileSpeed=STAT_RANGES["projectileSpeed"].max,
        lifetime=STAT_RANGES["lifetime"].max,
    )
    stats, report = clamp_stats(maxed)

    assert report.budgetScaled is True
    assert report.rawTotal == 4.0
    # 반올림 오차만큼의 여유만 둔다
    assert normalized_total(stats) <= STAT_BUDGET + 0.05


def test_modest_stats_are_untouched():
    modest = ForgeStats(damage=5, shotsPerSecond=3, projectileSpeed=8, lifetime=4)
    stats, report = clamp_stats(modest)

    assert report.budgetScaled is False
    assert report.clamped == []
    assert stats.damage == 5
    assert stats.shotsPerSecond == 3
    assert stats.projectileSpeed == 8
    assert stats.lifetime == 4


def test_budget_scaling_keeps_relative_shape():
    """한 스탯만 깎지 말고 비율을 유지해야 무기 성격이 보존된다."""
    lopsided = ForgeStats(
        damage=STAT_RANGES["damage"].max,
        shotsPerSecond=STAT_RANGES["shotsPerSecond"].max,
        projectileSpeed=STAT_RANGES["projectileSpeed"].min,
        lifetime=STAT_RANGES["lifetime"].min,
    )
    stats, report = clamp_stats(lopsided)

    assert report.budgetScaled is False  # 정규화 합 2.0 < 2.2 라 손대지 않는다
    # 최소값이던 스탯은 그대로 최소값
    assert stats.projectileSpeed == STAT_RANGES["projectileSpeed"].min
    assert stats.lifetime == STAT_RANGES["lifetime"].min


def test_non_finite_falls_back_to_base():
    stats, _ = clamp_stats(
        ForgeStats(
            damage=math.nan,
            shotsPerSecond=math.inf,
            projectileSpeed=8,
            lifetime=4,
        )
    )

    assert stats.damage == STAT_RANGES["damage"].base
    assert stats.shotsPerSecond == STAT_RANGES["shotsPerSecond"].base


def test_damage_is_integer():
    stats, _ = clamp_stats(
        ForgeStats(damage=7.6, shotsPerSecond=3.333, projectileSpeed=8, lifetime=4)
    )

    assert stats.damage == int(stats.damage)
    assert stats.shotsPerSecond == 3.33
