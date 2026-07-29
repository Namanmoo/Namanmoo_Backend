"""무기 스탯 스키마와 허용 범위.

모델 응답은 믿지 않는다 — 여기서 형태를 강제하고 clamp.py에서 범위를 강제한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StatRange(BaseModel):
    min: float
    max: float
    base: float


# 게임 쪽 PlayerSwordShooter의 기본값(5 / 3 / 8 / 4)을 가운데쯤에 두고 잡은 범위
STAT_RANGES: dict[str, StatRange] = {
    "damage": StatRange(min=1, max=30, base=5),
    "shotsPerSecond": StatRange(min=0.5, max=8, base=3),
    "projectileSpeed": StatRange(min=3, max=20, base=8),
    "lifetime": StatRange(min=0.5, max=8, base=4),
}

STAT_KEYS = tuple(STAT_RANGES.keys())

# 정규화 스탯 합의 상한. 스탯 4종을 각자 0~1로 환산해 더한 값이 이 값을 넘으면
# 비율을 유지한 채 줄인다. 전부 최대로 찍는 무기를 막는 유일한 방어선이다.
STAT_BUDGET = 2.2


class ForgeStats(BaseModel):
    damage: float
    shotsPerSecond: float
    projectileSpeed: float
    lifetime: float


class ForgeLlmResult(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    flavor: str = Field(min_length=1, max_length=120)
    stats: ForgeStats


class ClampReport(BaseModel):
    # 범위를 벗어나 잘린 스탯 이름
    clamped: list[str]
    # 버젯 초과로 전체를 줄였는가
    budgetScaled: bool
    rawTotal: float
    finalTotal: float


class ForgeVariant(BaseModel):
    version: Literal[1, 2, 3]
    # base64 PNG. 1번은 클라이언트가 가진 원본을 쓰므로 항상 빈 문자열
    image: str
    # 생성에 실패해 원본으로 대체해야 하는가
    failed: bool


class ForgeResponse(BaseModel):
    name: str
    flavor: str
    stats: ForgeStats
    variants: list[ForgeVariant]
    # 'gemini' | 'mock' — 클라이언트가 목 결과임을 표시할 수 있게
    source: str
    # 스탯 생성에 끝내 실패해 기본 무기가 지급됐는가
    fallback: bool
    clamp: ClampReport


def default_forge_result() -> ForgeLlmResult:
    """모델이 끝내 쓸 만한 답을 못 냈을 때 지급되는 무기."""
    return ForgeLlmResult(
        name="연필 막대",
        flavor="대장간이 답을 내지 못해, 구석에 있던 튼튼한 연필을 대신 쥐여 주었다.",
        stats=ForgeStats(
            damage=STAT_RANGES["damage"].base,
            shotsPerSecond=STAT_RANGES["shotsPerSecond"].base,
            projectileSpeed=STAT_RANGES["projectileSpeed"].base,
            lifetime=STAT_RANGES["lifetime"].base,
        ),
    )
