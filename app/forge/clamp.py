"""스탯 범위·버젯 강제 (순수 함수 — 테스트 대상).

모델은 얼마든지 과한 숫자를 낼 수 있으므로 게임에 들어가기 전 여기서 깎는다.
"""

from __future__ import annotations

import math

from .schema import STAT_BUDGET, STAT_KEYS, STAT_RANGES, ClampReport, ForgeStats


def _clamp_to_range(key: str, value: float) -> float:
    r = STAT_RANGES[key]
    if not math.isfinite(value):
        return r.base
    return min(r.max, max(r.min, value))


def _normalize(key: str, value: float) -> float:
    """min일 때 0, max일 때 1."""
    r = STAT_RANGES[key]
    return (value - r.min) / (r.max - r.min)


def _denormalize(key: str, ratio: float) -> float:
    r = STAT_RANGES[key]
    return r.min + ratio * (r.max - r.min)


def _round(key: str, value: float) -> float:
    # damage만 정수 — 나머지는 소수 둘째 자리까지
    return float(round(value)) if key == "damage" else round(value, 2)


def clamp_stats(stats: ForgeStats) -> tuple[ForgeStats, ClampReport]:
    raw = stats.model_dump()
    clamped: list[str] = []
    bounded: dict[str, float] = {}

    for key in STAT_KEYS:
        value = _clamp_to_range(key, float(raw[key]))
        if value != raw[key]:
            clamped.append(key)
        bounded[key] = value

    ratios = {key: _normalize(key, bounded[key]) for key in STAT_KEYS}
    raw_total = sum(ratios.values())

    budget_scaled = False
    if raw_total > STAT_BUDGET and raw_total > 0:
        # 비율을 유지한 채 전체를 줄인다 — 어느 하나만 깎으면 무기 성격이 바뀐다
        scale = STAT_BUDGET / raw_total
        budget_scaled = True
        for key in STAT_KEYS:
            bounded[key] = _denormalize(key, ratios[key] * scale)

    final = {key: _round(key, bounded[key]) for key in STAT_KEYS}
    final_total = sum(_normalize(key, final[key]) for key in STAT_KEYS)

    return ForgeStats(**final), ClampReport(
        clamped=clamped,
        budgetScaled=budget_scaled,
        rawTotal=round(raw_total, 3),
        finalTotal=round(final_total, 3),
    )
