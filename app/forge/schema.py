"""무기 생성 스키마 — 3축(분류 × 궤도 × 효과) 모델.

모델 응답은 믿지 않는다 — 여기서 형태를 강제하고 clamp.py에서 카탈로그와 예산을 강제한다.
"무엇을 고를 수 있는가"는 weapon-catalog.json이 정하므로 여기에는 값 목록을 두지 않는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .catalog import WeaponCatalog, load_catalog

# AI 개입 단계. 클라이언트 슬라이더가 그대로 보낸다.
#   0 = 개입 없음      — 그린 그림을 그대로 쓴다 (이미지 생성 호출 없음)
#   1 = 조금 멋있게    — 형태를 유지하고 선·색만 다듬는다
#   2 = 완전 멋있게    — 컨셉만 살려 새로 그린다
Stage = Literal[0, 1, 2]
MAX_STAGE = 2


class ParamPair(BaseModel):
    """파라미터 한 개.

    사전(dict) 대신 key/value 쌍의 배열로 주고받는다 — Gemini 구조화 출력은
    키가 정해지지 않은 OBJECT를 표현할 수 없어서, 자유 사전을 요구하면
    스키마를 못 만들거나 모델이 제멋대로 형태를 바꾼다.
    """

    key: str
    value: float


def pairs_to_dict(pairs: list[ParamPair] | None) -> dict[str, float]:
    return {p.key: p.value for p in (pairs or [])}


def dict_to_pairs(values: dict[str, float]) -> list[ParamPair]:
    return [ParamPair(key=k, value=v) for k, v in values.items()]


class ForgeDelivery(BaseModel):
    """궤도 — 무기 하나당 정확히 하나."""

    deliveryId: str
    params: list[ParamPair] = Field(default_factory=list)


class ForgeEffectEntry(BaseModel):
    """효과 블록 하나 = 트리거 + 효과 + 파라미터."""

    effectId: str
    triggerId: str
    params: list[ParamPair] = Field(default_factory=list)


class ForgeLlmResult(BaseModel):
    """모델이 내놓는 날것. 카탈로그 대조는 clamp.py가 한다."""

    name: str = Field(min_length=1, max_length=24)
    flavor: str = Field(min_length=1, max_length=200)
    category: str
    weaponType: str
    # 키는 분류마다 다르다 (근접 reach/attackArc, 원거리 projectileSpeed/lifetime)
    stats: list[ParamPair] = Field(default_factory=list)
    delivery: ForgeDelivery
    effects: list[ForgeEffectEntry] = Field(default_factory=list)
    # 그림의 성의 0~1. 예산 보너스에 쓰인다.
    effortScore: float = 0.0

    @field_validator("flavor", mode="before")
    @classmethod
    def _truncate_flavor(cls, value: object) -> object:
        # 문장이 조금 길다고 무기 전체를 재시도·폴백으로 보내지 않는다 — 잘라서 살린다
        if isinstance(value, str):
            value = value.strip()
            if len(value) > 200:
                return value[:199] + "…"
        return value


class DroppedEntry(BaseModel):
    id: str
    reason: str


class EffectCost(BaseModel):
    effectId: str
    triggerId: str
    cost: float


class BudgetReport(BaseModel):
    base: float
    effortBonus: float
    totalBudget: float
    totalCost: float
    statCost: float
    deliveryCost: float
    effectCosts: list[EffectCost]
    # 카탈로그에 없거나 이 분류에 허용되지 않아 버린 것
    dropped: list[DroppedEntry]
    # 가변 비용을 줄일 때 적용한 배율 (안 줄였으면 None)
    clampScale: float | None


class SlashShape(BaseModel):
    """검기 참격 실루엣 — 5×5 그리드 점을 이어 채운 다각형.

    무기를 만들 때 한 번 랜덤으로 정해 그대로 저장한다 — 같은 무기는
    언제나 같은 참격이 나간다. points는 위→아래 순서로 x,y가 번갈아 오는
    평면 배열이다 (Unity JsonUtility가 중첩 배열을 읽지 못한다). 좌표 -1~1.
    """

    curved: bool
    points: list[float] = Field(default_factory=list)


class ForgeWeapon(BaseModel):
    """검증·클램프를 통과한 최종 무기. 클라이언트가 그대로 조립한다.

    stats도 사전이 아니라 key/value 배열이다 — Unity의 JsonUtility는 Dictionary를
    파싱하지 못한다. 파라미터와 형태를 맞춰 두면 클라이언트 파서가 하나로 끝난다.
    """

    category: str
    weaponType: str
    stats: list[ParamPair] = Field(default_factory=list)
    delivery: ForgeDelivery
    effects: list[ForgeEffectEntry]
    # 검기(blade_wave) 효과가 있을 때만 채워진다
    slashShape: SlashShape | None = None

    @property
    def stats_map(self) -> dict[str, float]:
        return pairs_to_dict(self.stats)


class ForgeResponse(BaseModel):
    name: str
    flavor: str
    weapon: ForgeWeapon
    # 요청한 단계를 그대로 돌려준다 (클라이언트가 응답을 확인할 수 있게)
    stage: Stage
    # base64 PNG. 0단계이거나 생성이 실패하면 빈 문자열 — 클라이언트가 원본을 쓴다
    image: str
    # 생성에 실패해 원본으로 대체해야 하는가 (0단계는 실패가 아니므로 false)
    imageFailed: bool
    # 'mock' 또는 'stats=...,image=...' — 클라이언트가 목 결과임을 표시할 수 있게
    source: str
    # 끝내 실패해 기본 무기가 지급됐는가
    fallback: bool
    budget: BudgetReport


def _number() -> dict:
    return {"type": "NUMBER"}


def _param_pairs() -> dict:
    return {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {"key": {"type": "STRING"}, "value": _number()},
            "required": ["key", "value"],
        },
    }


def weapon_response_schema(catalog: WeaponCatalog | None = None) -> dict:
    """Gemini 구조화 출력용 스키마.

    이걸 주지 않으면 모델이 설명을 곁들인 마크다운을 내보내 파싱이 깨진다
    (실제로 "**Flavor:** * Name: ..." 같은 응답을 받았다).

    id 후보는 enum으로 박아 넣는다 — 문자열을 자유롭게 두면 카탈로그에 없는
    효과를 지어내고, 그건 전부 clamp에서 버려져 무기가 빈껍데기가 된다.
    """
    catalog = catalog or load_catalog()

    return {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING"},
            "flavor": {"type": "STRING"},
            "category": {"type": "STRING", "enum": list(catalog.category_ids)},
            "weaponType": {
                "type": "STRING",
                "enum": sorted({t for c in catalog.categories for t in c.weapon_types}),
            },
            "stats": _param_pairs(),
            "delivery": {
                "type": "OBJECT",
                "properties": {
                    "deliveryId": {
                        "type": "STRING",
                        "enum": [d.id for d in catalog.deliveries],
                    },
                    "params": _param_pairs(),
                },
                "required": ["deliveryId", "params"],
            },
            "effects": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "effectId": {"type": "STRING", "enum": [e.id for e in catalog.effects]},
                        "triggerId": {"type": "STRING", "enum": [t.id for t in catalog.triggers]},
                        "params": _param_pairs(),
                    },
                    "required": ["effectId", "triggerId", "params"],
                },
            },
            "effortScore": _number(),
        },
        "required": [
            "name",
            "flavor",
            "category",
            "weaponType",
            "stats",
            "delivery",
            "effects",
            "effortScore",
        ],
    }


def default_forge_result(catalog: WeaponCatalog | None = None) -> ForgeLlmResult:
    """모델이 끝내 쓸 만한 답을 못 냈을 때 지급되는 무기.

    효과 없는 평범한 원거리 무기 — 재미는 없지만 그 판은 그대로 굴러간다.
    """
    catalog = catalog or load_catalog()
    ranged = catalog.category("ranged") or catalog.categories[0]
    # 궤도는 무기 종류와 1:1 — 가장 싼 궤도를 고르고 그 짝인 종류를 쓴다
    delivery = catalog.default_delivery(ranged.id)
    weapon_type = delivery.weapon_type or ranged.weapon_types[0]

    return ForgeLlmResult(
        name="연필 막대",
        flavor="대장간이 답을 내지 못해, 구석에 있던 튼튼한 연필을 대신 쥐여 주었다.",
        category=ranged.id,
        weaponType=weapon_type,
        # 각 스탯을 범위의 40% 지점에 — 기존 검(5/3/8/4)과 비슷한 자리다
        stats=[ParamPair(key=s.key, value=round(s.denormalize(0.4), 2)) for s in ranged.stats],
        delivery=ForgeDelivery(deliveryId=delivery.id, params=[]),
        effects=[],
        effortScore=0.0,
    )
