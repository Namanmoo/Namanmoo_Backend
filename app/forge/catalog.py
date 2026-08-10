"""무기 카탈로그 로더와 비용 모델 (순수 함수 — 테스트 대상).

weapon-catalog.json이 단일 원본이다. 여기서는 그 JSON을 읽고 비용만 계산한다.
"AI가 고를 수 있는 것"의 정의가 전부 이 파일 밖(JSON)에 있어야, 효과를 덜어낼 때
JSON 블록만 지우면 되고 파이썬 코드는 손대지 않는다.

비용 모델:
  스탯   = 정규화(0~1) × weight        — 전부 최대면 그것만으로 weaponBase를 다 쓴다
  궤도/효과 = baseCost + Σ(스텝 수 × costPerStep)
  costPerStep이 음수인 파라미터(긴 쿨다운 등)는 값을 올릴수록 싸지지만,
  항목당 비용은 0 밑으로 내려가지 않는다 — 안 그러면 느린 옵션이 예산을 벌어들인다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

CATALOG_PATH = Path(__file__).with_name("weapon-catalog.json")


@dataclass(frozen=True)
class CatalogParam:
    key: str
    min: float
    max: float
    step: float
    cost_per_step: float

    def clamp(self, value: float) -> float:
        """[min,max]로 자르고 step 격자에 스냅한다."""
        bounded = min(self.max, max(self.min, value))
        steps = round((bounded - self.min) / self.step)
        return round(self.min + steps * self.step, 3)

    def steps_from_min(self, value: float) -> int:
        return max(0, round((value - self.min) / self.step))


@dataclass(frozen=True)
class CatalogStat:
    key: str
    min: float
    max: float
    weight: float

    def clamp(self, value: float) -> float:
        return min(self.max, max(self.min, value))

    def normalize(self, value: float) -> float:
        """min일 때 0, max일 때 1."""
        span = self.max - self.min
        return 0.0 if span == 0 else (value - self.min) / span

    def denormalize(self, ratio: float) -> float:
        return self.min + ratio * (self.max - self.min)


@dataclass(frozen=True)
class CatalogCategory:
    id: str
    display_name: str
    description: str
    weapon_types: tuple[str, ...]
    stats: tuple[CatalogStat, ...]
    # damage × 연사 속도의 상한. None이면 상한 없음. 범위 클램프는 스탯을 하나씩만
    # 자르므로 곱은 여기서 따로 강제해야 한다 (clamp.py).
    max_dps: float | None = None

    @property
    def stat_keys(self) -> tuple[str, ...]:
        return tuple(s.key for s in self.stats)

    def stat(self, key: str) -> CatalogStat | None:
        return next((s for s in self.stats if s.key == key), None)

    def dps_pair(self) -> tuple[CatalogStat, CatalogStat] | None:
        """(damage 스탯, 연사 속도 스탯). 연사 속도는 키가 PerSecond로 끝나는 스탯이다."""
        damage = self.stat("damage")
        rate = next((s for s in self.stats if s.key.endswith("PerSecond")), None)
        return (damage, rate) if damage and rate else None


@dataclass(frozen=True)
class CatalogEntry:
    """궤도·효과·트리거가 공유하는 형태 — id + 설명 + 비용 + 파라미터."""

    id: str
    display_name: str
    description: str
    base_cost: float
    params: tuple[CatalogParam, ...]
    categories: tuple[str, ...]  # 빈 튜플이면 분류를 가리지 않는다 (트리거)
    # 궤도 전용 — 이 궤도와 1:1로 짝인 무기 종류. 빈 문자열이면 짝이 없어 뽑히지 않는다.
    weapon_type: str = ""

    def allows(self, category: str) -> bool:
        return not self.categories or category in self.categories

    def param(self, key: str) -> CatalogParam | None:
        return next((p for p in self.params if p.key == key), None)

    def cost(self, params: dict[str, float]) -> float:
        """항목 하나의 비용. 0 밑으로는 내려가지 않는다."""
        total = self.base_cost
        for p in self.params:
            total += p.steps_from_min(params.get(p.key, p.min)) * p.cost_per_step
        return max(0.0, round(total, 3))


@dataclass(frozen=True)
class Budget:
    weapon_base: float
    effort_bonus_max: float
    max_effects: int


class WeaponCatalog:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.version: str = raw["version"]
        self.categories = tuple(_read_category(c) for c in raw["categories"])
        self.deliveries = tuple(_read_entry(d) for d in raw["deliveries"])
        self.triggers = tuple(_read_entry(t) for t in raw["triggers"])
        self.effects = tuple(_read_entry(e) for e in raw["effects"])
        budget = raw["budget"]
        self.budget = Budget(
            weapon_base=float(budget["weaponBase"]),
            effort_bonus_max=float(budget["effortBonusMax"]),
            max_effects=int(budget["maxEffects"]),
        )
        self._validate()

    # ── 조회 ────────────────────────────────────────────────────────

    def category(self, category_id: str) -> CatalogCategory | None:
        return next((c for c in self.categories if c.id == category_id), None)

    def delivery(self, delivery_id: str) -> CatalogEntry | None:
        return next((d for d in self.deliveries if d.id == delivery_id), None)

    def trigger(self, trigger_id: str) -> CatalogEntry | None:
        return next((t for t in self.triggers if t.id == trigger_id), None)

    def effect(self, effect_id: str) -> CatalogEntry | None:
        return next((e for e in self.effects if e.id == effect_id), None)

    @property
    def category_ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.categories)

    def deliveries_for(self, category: str) -> tuple[CatalogEntry, ...]:
        return tuple(d for d in self.deliveries if d.allows(category))

    def effects_for(self, category: str) -> tuple[CatalogEntry, ...]:
        return tuple(e for e in self.effects if e.allows(category))

    def delivery_for_type(self, weapon_type: str) -> CatalogEntry | None:
        """무기 종류와 1:1로 짝인 궤도. 검=swing, 도끼=spin, 창=thrust 식이다."""
        return next((d for d in self.deliveries if d.weapon_type == weapon_type), None)

    def default_delivery(self, category: str) -> CatalogEntry:
        """그 분류에서 가장 싼 궤도 — 궤도가 유효하지 않거나 예산이 모자랄 때의 바닥."""
        options = self.deliveries_for(category)
        if not options:
            raise ValueError(f"'{category}' 분류에 쓸 수 있는 궤도가 카탈로그에 없습니다.")
        return min(options, key=lambda d: d.base_cost)

    # ── 비용 ────────────────────────────────────────────────────────

    def stat_cost(self, category: CatalogCategory, stats: dict[str, float]) -> float:
        total = 0.0
        for stat in category.stats:
            total += stat.weight * stat.normalize(stat.clamp(stats.get(stat.key, stat.min)))
        return round(total, 3)

    # ── 무결성 ──────────────────────────────────────────────────────

    def _validate(self) -> None:
        """카탈로그 자체의 앞뒤가 맞는지 — 잘못 편집한 JSON을 서버 기동 때 잡는다."""
        problems: list[str] = []
        known = set(self.category_ids)

        for name, entries in (("궤도", self.deliveries), ("효과", self.effects)):
            for entry in entries:
                unknown = set(entry.categories) - known
                if unknown:
                    problems.append(f"{name} '{entry.id}'가 없는 분류를 가리킵니다: {sorted(unknown)}")
                if not entry.categories:
                    problems.append(f"{name} '{entry.id}'에 categories가 비어 있습니다.")

        for category in self.categories:
            if not self.deliveries_for(category.id):
                problems.append(f"분류 '{category.id}'에 쓸 수 있는 궤도가 없습니다.")
            if not category.stats:
                problems.append(f"분류 '{category.id}'에 스탯이 정의되어 있지 않습니다.")
            if category.max_dps is not None:
                pair = category.dps_pair()
                if pair is None:
                    problems.append(
                        f"분류 '{category.id}'에 maxDps가 있는데 damage/연사 스탯 짝이 없습니다."
                    )
                elif pair[0].max * pair[1].min > category.max_dps:
                    # 상한 초과 시 연사를 깎는 방식이라, 최대 damage가 최소 연사로도
                    # 상한을 넘으면 그 damage는 어떤 무기도 쓸 수 없다
                    problems.append(
                        f"분류 '{category.id}'의 damage 최대치가 최소 연사로도 maxDps를 넘습니다."
                    )
            for weapon_type in category.weapon_types:
                matches = [d for d in self.deliveries if d.weapon_type == weapon_type]
                if len(matches) != 1:
                    problems.append(
                        f"무기 종류 '{weapon_type}'의 궤도가 1개여야 하는데 {len(matches)}개입니다."
                    )
                elif not matches[0].allows(category.id):
                    problems.append(
                        f"무기 종류 '{weapon_type}'의 궤도 '{matches[0].id}'가 '{category.id}' 분류에 없습니다."
                    )

        for entries in (self.deliveries, self.effects, self.triggers):
            for entry in entries:
                for p in entry.params:
                    if p.step <= 0:
                        problems.append(f"'{entry.id}.{p.key}'의 step이 0 이하입니다.")
                    elif p.max < p.min:
                        problems.append(f"'{entry.id}.{p.key}'의 max가 min보다 작습니다.")

        for name, ids in (
            ("분류", self.category_ids),
            ("궤도", tuple(d.id for d in self.deliveries)),
            ("트리거", tuple(t.id for t in self.triggers)),
            ("효과", tuple(e.id for e in self.effects)),
        ):
            duplicates = {i for i in ids if list(ids).count(i) > 1}
            if duplicates:
                problems.append(f"{name} id가 중복입니다: {sorted(duplicates)}")

        if problems:
            raise ValueError("weapon-catalog.json이 올바르지 않습니다:\n- " + "\n- ".join(problems))


def _read_params(raw: Iterable[dict[str, Any]]) -> tuple[CatalogParam, ...]:
    return tuple(
        CatalogParam(
            key=p["key"],
            min=float(p["min"]),
            max=float(p["max"]),
            step=float(p["step"]),
            cost_per_step=float(p["costPerStep"]),
        )
        for p in raw
    )


def _read_entry(raw: dict[str, Any]) -> CatalogEntry:
    return CatalogEntry(
        id=raw["id"],
        display_name=raw["displayName_ko"],
        description=raw["description_ko"],
        base_cost=float(raw.get("baseCost", 0)),
        params=_read_params(raw.get("params", [])),
        categories=tuple(raw.get("categories", ())),
        weapon_type=str(raw.get("weaponType", "")),
    )


def _read_category(raw: dict[str, Any]) -> CatalogCategory:
    max_dps = raw.get("maxDps")
    return CatalogCategory(
        id=raw["id"],
        display_name=raw["displayName_ko"],
        description=raw["description_ko"],
        weapon_types=tuple(raw["weaponTypes"]),
        max_dps=float(max_dps) if max_dps is not None else None,
        stats=tuple(
            CatalogStat(
                key=s["key"], min=float(s["min"]), max=float(s["max"]), weight=float(s["weight"])
            )
            for s in raw["stats"]
        ),
    )


@lru_cache(maxsize=1)
def load_catalog(path: str | None = None) -> WeaponCatalog:
    """카탈로그를 읽어 캐시한다. 테스트는 path를 넘겨 다른 카탈로그를 쓸 수 있다."""
    target = Path(path) if path else CATALOG_PATH
    return WeaponCatalog(json.loads(target.read_text(encoding="utf-8")))
