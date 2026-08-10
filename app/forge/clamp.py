"""카탈로그 대조와 예산 강제 (순수 함수 — 테스트 대상).

모델은 없는 효과를 지어내고 얼마든지 과한 숫자를 낸다. 게임에 들어가기 전 여기서
카탈로그에 대조하고 예산 안으로 깎는다. AIGame validate.ts의 사상을 따른다 —
AI의 자기 신고(effortScore 포함)를 그대로 믿지 않는다.

깎는 순서:
  1. 가변 비용(스탯 + costPerStep>0 파라미터)을 비율 유지한 채 축소
  2. 그래도 넘치면 효과를 뒤에서부터 버린다
  3. 그래도 넘치면 궤도를 그 분류의 가장 싼 것으로 내린다
스탯 최소 + 기본 궤도 + 효과 0이면 비용이 0이므로 이 절차는 반드시 끝난다.
"""

from __future__ import annotations

import math

from .catalog import CatalogCategory, CatalogEntry, WeaponCatalog, load_catalog
from .schema import (
    BudgetReport,
    DroppedEntry,
    EffectCost,
    ForgeDelivery,
    ForgeEffectEntry,
    ForgeLlmResult,
    ForgeWeapon,
    dict_to_pairs,
    pairs_to_dict,
)

# 모델이 스탯을 빠뜨렸을 때 놓는 자리 (범위의 40% 지점)
MISSING_STAT_RATIO = 0.4

# 축소 반복 상한 — 수렴하지만 만약을 대비한 빗장
_MAX_PASSES = 50


def _finite(value: float, fallback: float) -> float:
    return value if math.isfinite(value) else fallback


def _positive_params(entry: CatalogEntry) -> tuple[str, ...]:
    """값을 올리면 비싸지는 파라미터 — 축소 대상."""
    return tuple(p.key for p in entry.params if p.cost_per_step > 0)


def _floor_params(entry: CatalogEntry, params: dict[str, float]) -> dict[str, float]:
    """축소 가능한 파라미터를 전부 최소로 내린 상태 — 더는 못 깎는 바닥."""
    floored = dict(params)
    for p in entry.params:
        if p.cost_per_step > 0:
            floored[p.key] = p.min
    return floored


def _split_cost(entry: CatalogEntry, params: dict[str, float]) -> tuple[float, float]:
    """(고정 비용, 가변 비용). 항목 비용이 0으로 바닥을 치는 경우까지 앞뒤가 맞게 나눈다."""
    full = entry.cost(params)
    floor = entry.cost(_floor_params(entry, params))
    variable = max(0.0, full - floor)
    return full - variable, variable


def _scale_params(entry: CatalogEntry, params: dict[str, float], factor: float) -> dict[str, float]:
    scaled = dict(params)
    for p in entry.params:
        if p.cost_per_step <= 0:
            continue
        steps = p.steps_from_min(params.get(p.key, p.min))
        scaled[p.key] = round(p.min + math.floor(steps * factor) * p.step, 3)
    return scaled


def _resolve_category(catalog: WeaponCatalog, raw: str) -> CatalogCategory:
    return catalog.category(raw) or catalog.category("ranged") or catalog.categories[0]


def _resolve_stats(category: CatalogCategory, raw: dict[str, float]) -> dict[str, float]:
    """그 분류의 스탯 키만 남긴다 — 근접 무기에 딸려 온 projectileSpeed 따위는 버린다."""
    resolved: dict[str, float] = {}
    for stat in category.stats:
        value = _finite(float(raw.get(stat.key, stat.denormalize(MISSING_STAT_RATIO))),
                        stat.denormalize(MISSING_STAT_RATIO))
        resolved[stat.key] = stat.clamp(value)
    _enforce_dps_cap(category, resolved)
    return resolved


def _enforce_dps_cap(category: CatalogCategory, stats: dict[str, float]) -> None:
    """damage × 연사 속도의 곱을 maxDps 안으로 — 범위 클램프는 곱을 못 막는다.

    한 방의 무게(damage)는 무기의 정체성이라 남기고 연사 속도를 깎는다.
    판정은 Unity가 실제로 쓸 값으로 한다 — ForgeDto가 damage를 정수로
    반올림하므로, 서버 숫자로는 상한 안이어도 반올림 후 넘을 수 있다.
    이후 예산 축소는 두 스탯을 같이 줄이므로 곱이 다시 늘지 않는다.
    """
    if category.max_dps is None:
        return
    pair = category.dps_pair()
    if pair is None:
        return
    damage_stat, rate_stat = pair
    client_damage = max(
        damage_stat.min, float(round(stats.get(damage_stat.key, damage_stat.min)))
    )
    rate = stats.get(rate_stat.key, rate_stat.min)
    if client_damage * rate <= category.max_dps:
        return
    stats[damage_stat.key] = client_damage
    stats[rate_stat.key] = max(
        rate_stat.min, math.floor(category.max_dps / client_damage * 100) / 100
    )


def _resolve_delivery(
    catalog: WeaponCatalog,
    category: CatalogCategory,
    weapon_type: str,
    raw: ForgeDelivery,
    dropped: list[DroppedEntry],
) -> tuple[CatalogEntry, dict[str, float]]:
    # 궤도는 무기 종류와 1:1이다 — 검=swing, 도끼=spin, 창=thrust,
    # 투사체(Projectile)=straight, 유도탄(Missile)=homing, 부메랑=boomerang.
    # 모델이 뭘 고르든 짝으로 바꾼다.
    entry = catalog.delivery_for_type(weapon_type)
    if entry is None or not entry.allows(category.id):
        entry = catalog.default_delivery(category.id)

    if raw.deliveryId and raw.deliveryId != entry.id:
        dropped.append(
            DroppedEntry(id=raw.deliveryId, reason=f"'{weapon_type}'의 궤도는 '{entry.id}' 하나다")
        )

    raw_params = pairs_to_dict(raw.params)
    params = {p.key: p.clamp(_finite(float(raw_params.get(p.key, p.min)), p.min)) for p in entry.params}
    return entry, params


def _resolve_effects(
    catalog: WeaponCatalog,
    category: CatalogCategory,
    raw_effects: list[ForgeEffectEntry],
    dropped: list[DroppedEntry],
) -> list[tuple[CatalogEntry, CatalogEntry, dict[str, float]]]:
    """[(효과, 트리거, 파라미터)]. 카탈로그에 없거나 분류가 안 맞으면 버린다."""
    resolved: list[tuple[CatalogEntry, CatalogEntry, dict[str, float]]] = []
    seen: set[tuple[str, str]] = set()

    for item in raw_effects:
        effect = catalog.effect(item.effectId)
        trigger = catalog.trigger(item.triggerId)

        if effect is None:
            dropped.append(DroppedEntry(id=item.effectId, reason="카탈로그에 없는 효과"))
            continue
        if trigger is None:
            dropped.append(DroppedEntry(id=item.triggerId, reason="카탈로그에 없는 트리거"))
            continue
        if not effect.allows(category.id):
            dropped.append(
                DroppedEntry(
                    id=effect.id, reason=f"'{category.display_name}' 분류에 쓸 수 없는 효과"
                )
            )
            continue

        key = (effect.id, trigger.id)
        if key in seen:
            dropped.append(DroppedEntry(id=effect.id, reason="같은 효과+트리거 조합이 중복"))
            continue
        if len(resolved) >= catalog.budget.max_effects:
            dropped.append(
                DroppedEntry(id=effect.id, reason=f"효과는 최대 {catalog.budget.max_effects}개")
            )
            continue
        seen.add(key)

        # 트리거 파라미터를 먼저 깔고 효과 파라미터를 덮는다 — 키가 겹치면 효과 쪽이 이긴다
        raw_params = pairs_to_dict(item.params)
        params: dict[str, float] = {}
        for source in (trigger, effect):
            for p in source.params:
                params[p.key] = p.clamp(_finite(float(raw_params.get(p.key, p.min)), p.min))
        resolved.append((effect, trigger, params))

    return resolved


def _effect_cost(effect: CatalogEntry, trigger: CatalogEntry, params: dict[str, float]) -> float:
    """효과 비용 = 효과 항목 + 트리거 항목. 트리거는 baseCost가 없고 할인만 준다."""
    trigger_delta = trigger.cost(params) - trigger.base_cost
    return max(0.0, round(effect.cost(params) + trigger_delta, 3))


def clamp_weapon(
    result: ForgeLlmResult, catalog: WeaponCatalog | None = None
) -> tuple[ForgeWeapon, BudgetReport]:
    """모델 결과를 카탈로그·예산에 맞춰 깎아 최종 무기로 만든다."""
    catalog = catalog or load_catalog()
    dropped: list[DroppedEntry] = []

    category = _resolve_category(catalog, result.category)
    weapon_type = (
        result.weaponType if result.weaponType in category.weapon_types else category.weapon_types[0]
    )
    if weapon_type != result.weaponType:
        dropped.append(
            DroppedEntry(id=result.weaponType, reason=f"'{category.display_name}'의 무기 종류가 아님")
        )

    stats = _resolve_stats(category, pairs_to_dict(result.stats))
    delivery_entry, delivery_params = _resolve_delivery(
        catalog, category, weapon_type, result.delivery, dropped)
    effects = _resolve_effects(catalog, category, result.effects, dropped)

    effort = min(1.0, max(0.0, _finite(result.effortScore, 0.0)))
    base = catalog.budget.weapon_base
    effort_bonus = round(catalog.budget.effort_bonus_max * effort, 3)
    total_budget = base + effort_bonus

    clamp_scale: float | None = None

    for _ in range(_MAX_PASSES):
        stat_cost = catalog.stat_cost(category, stats)
        delivery_fixed, delivery_variable = _split_cost(delivery_entry, delivery_params)
        # 트리거 할인은 고정분에 얹는다 (값을 올릴수록 싸지므로 축소 대상이 아니다)
        effect_fixed = 0.0
        effect_variable = 0.0
        for effect, trigger, params in effects:
            entry_fixed, entry_variable = _split_cost(effect, params)
            effect_fixed += entry_fixed + (trigger.cost(params) - trigger.base_cost)
            effect_variable += entry_variable

        fixed = delivery_fixed + effect_fixed
        variable = stat_cost + delivery_variable + effect_variable
        total = round(fixed + variable, 3)

        if total <= total_budget:
            break

        if fixed <= total_budget and variable > 0:
            # 1) 비율을 유지한 채 가변 비용을 줄인다 — 어느 하나만 깎으면 무기 성격이 바뀐다
            factor = max(0.0, (total_budget - fixed) / variable)
            clamp_scale = round(factor, 3)
            for stat in category.stats:
                stats[stat.key] = round(
                    stat.denormalize(stat.normalize(stats[stat.key]) * factor), 2
                )
            delivery_params = _scale_params(delivery_entry, delivery_params, factor)
            effects = [
                (effect, trigger, _scale_params(effect, params, factor))
                for effect, trigger, params in effects
            ]
        elif effects:
            # 2) 기본 비용만으로 넘치면 효과를 뒤에서부터 버린다
            effect, _trigger, _params = effects.pop()
            dropped.append(DroppedEntry(id=effect.id, reason="예산 초과로 제외"))
        else:
            # 3) 마지막으로 궤도를 가장 싼 것으로 내린다
            cheapest = catalog.default_delivery(category.id)
            if delivery_entry.id == cheapest.id:
                break
            dropped.append(DroppedEntry(id=delivery_entry.id, reason="예산 초과로 기본 궤도로 내림"))
            delivery_entry = cheapest
            delivery_params = {p.key: p.min for p in cheapest.params}

    stat_cost = catalog.stat_cost(category, stats)
    delivery_cost = delivery_entry.cost(delivery_params)
    effect_costs = [
        EffectCost(
            effectId=effect.id, triggerId=trigger.id, cost=_effect_cost(effect, trigger, params)
        )
        for effect, trigger, params in effects
    ]

    weapon = ForgeWeapon(
        category=category.id,
        weaponType=weapon_type,
        stats=dict_to_pairs({k: round(v, 2) for k, v in stats.items()}),
        delivery=ForgeDelivery(
            deliveryId=delivery_entry.id, params=dict_to_pairs(delivery_params)
        ),
        effects=[
            ForgeEffectEntry(
                effectId=effect.id, triggerId=trigger.id, params=dict_to_pairs(params)
            )
            for effect, trigger, params in effects
        ],
    )

    report = BudgetReport(
        base=base,
        effortBonus=effort_bonus,
        totalBudget=total_budget,
        totalCost=round(stat_cost + delivery_cost + sum(e.cost for e in effect_costs), 3),
        statCost=stat_cost,
        deliveryCost=delivery_cost,
        effectCosts=effect_costs,
        dropped=dropped,
        clampScale=clamp_scale,
    )
    return weapon, report


def clamp_existing_weapon(
    weapon: ForgeWeapon, catalog: WeaponCatalog | None = None
) -> tuple[ForgeWeapon, BudgetReport]:
    """이미 만들어진 무기를 다시 대조한다 — 무기고 저장처럼 클라이언트가 값을 보내는 경로용.

    effortScore를 1.0으로 두는 건 성의 보너스를 얼마나 받았는지 저장하지 않기 때문이다.
    여기서 막고 싶은 건 '예산 500짜리 무기를 밀어 넣는 것'이지 보너스 1~15점의 오차가 아니라,
    가장 너그러운 예산으로 검증한다.
    """
    return clamp_weapon(
        ForgeLlmResult(
            name="_",
            flavor="_",
            category=weapon.category,
            weaponType=weapon.weaponType,
            stats=weapon.stats,
            delivery=weapon.delivery,
            effects=weapon.effects,
            effortScore=1.0,
        ),
        catalog,
    )
