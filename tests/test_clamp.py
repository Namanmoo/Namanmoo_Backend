"""카탈로그 대조와 예산 강제 검증.

여기서 지키려는 것은 하나다 — 모델이 무슨 소리를 하든 게임에 들어가는 무기는
카탈로그 안에 있고 예산을 넘지 않는다.
"""

from __future__ import annotations

import pytest

from app.forge.catalog import load_catalog
from app.forge.clamp import clamp_existing_weapon, clamp_weapon
from app.forge.schema import (
    ForgeDelivery,
    ForgeEffectEntry,
    ForgeLlmResult,
    ParamPair,
    default_forge_result,
)


@pytest.fixture
def catalog():
    return load_catalog()


def make_result(
    *,
    category: str = "ranged",
    weapon_type: str | None = None,
    stats: dict[str, float] | None = None,
    delivery: str = "straight",
    delivery_params: dict[str, float] | None = None,
    effects: list[tuple[str, str, dict[str, float]]] | None = None,
    effort: float = 0.0,
) -> ForgeLlmResult:
    return ForgeLlmResult(
        name="시험용 무기",
        flavor="테스트가 두들겨 만든 무기다.",
        category=category,
        weaponType=weapon_type or ("Projectile" if category == "ranged" else "Sword"),
        stats=[ParamPair(key=k, value=v) for k, v in (stats or {}).items()],
        delivery=ForgeDelivery(
            deliveryId=delivery,
            params=[ParamPair(key=k, value=v) for k, v in (delivery_params or {}).items()],
        ),
        effects=[
            ForgeEffectEntry(
                effectId=e,
                triggerId=t,
                params=[ParamPair(key=k, value=v) for k, v in p.items()],
            )
            for e, t, p in (effects or [])
        ],
        effortScore=effort,
    )


def total_of(report) -> float:
    return report.statCost + report.deliveryCost + sum(e.cost for e in report.effectCosts)


# ── 카탈로그 대조 ────────────────────────────────────────────────────────


def test_지어낸_효과는_버려진다(catalog):
    weapon, report = clamp_weapon(
        make_result(effects=[("시간정지", "on_hit", {}), ("fire_dot", "on_hit", {})]), catalog
    )

    assert [e.effectId for e in weapon.effects] == ["fire_dot"]
    assert any(d.id == "시간정지" for d in report.dropped)


def test_지어낸_트리거는_버려진다(catalog):
    weapon, report = clamp_weapon(make_result(effects=[("fire_dot", "on_full_moon", {})]), catalog)

    assert weapon.effects == []
    assert any(d.id == "on_full_moon" for d in report.dropped)


def test_근접_무기에_원거리_전용_효과는_붙지_않는다(catalog):
    weapon, report = clamp_weapon(
        make_result(category="melee", delivery="swing", effects=[("pierce", "on_hit", {})]),
        catalog,
    )

    assert weapon.effects == []
    assert any(d.id == "pierce" for d in report.dropped)


def test_근접_무기에_원거리_궤도는_기본_궤도로_대체된다(catalog):
    weapon, report = clamp_weapon(make_result(category="melee", delivery="homing"), catalog)

    assert weapon.delivery.deliveryId == "swing"
    assert any(d.id == "homing" for d in report.dropped)


def test_없는_궤도는_무기_종류의_짝_궤도로_대체된다(catalog):
    # 종류가 Missile이므로 짝인 homing이 된다 — 기본 궤도(straight) 대체와 구분된다
    weapon, _ = clamp_weapon(make_result(weapon_type="Missile", delivery="워프"), catalog)

    assert weapon.delivery.deliveryId == "homing"


def test_궤도는_무기_종류와_1대1로_강제된다(catalog):
    # 도끼=spin, 검=swing, 창=thrust / 투사체=straight, 유도탄=homing, 부메랑=boomerang
    pairs = [
        ("melee", "Axe", "spin"),
        ("melee", "Sword", "swing"),
        ("melee", "Spear", "thrust"),
        ("ranged", "Projectile", "straight"),
        ("ranged", "Missile", "homing"),
        ("ranged", "Boomerang", "boomerang"),
    ]
    for category, weapon_type, expected in pairs:
        weapon, report = clamp_weapon(
            make_result(category=category, weapon_type=weapon_type, delivery="swing"),
            catalog,
        )
        assert weapon.delivery.deliveryId == expected, weapon_type
        if expected != "swing":
            assert any(d.id == "swing" for d in report.dropped)


def test_분류에_맞지_않는_무기종류는_교정된다(catalog):
    weapon, report = clamp_weapon(make_result(category="melee", weapon_type="Missile"), catalog)

    assert weapon.weaponType in catalog.category("melee").weapon_types
    assert any(d.id == "Missile" for d in report.dropped)


def test_다른_분류의_스탯키는_버려진다(catalog):
    weapon, _ = clamp_weapon(
        make_result(category="melee", delivery="swing", stats={"projectileSpeed": 20, "reach": 2}),
        catalog,
    )

    assert "projectileSpeed" not in weapon.stats_map
    assert set(weapon.stats_map) == set(catalog.category("melee").stat_keys)


def test_같은_효과_트리거_조합은_한_번만_남는다(catalog):
    weapon, report = clamp_weapon(
        make_result(effects=[("fire_dot", "on_hit", {}), ("fire_dot", "on_hit", {})]), catalog
    )

    assert len(weapon.effects) == 1
    assert any("중복" in d.reason for d in report.dropped)


def test_효과_개수_상한을_넘지_않는다(catalog):
    many = [
        ("fire_dot", "on_hit", {}),
        ("chill_slow", "on_hit", {}),
        ("shock", "on_hit", {}),
        ("poison_stack", "on_hit", {}),
        ("chain", "on_hit", {}),
    ]
    weapon, _ = clamp_weapon(make_result(effects=many), catalog)

    assert len(weapon.effects) <= catalog.budget.max_effects


# ── 파라미터 ────────────────────────────────────────────────────────────


def test_파라미터는_범위와_격자로_스냅된다(catalog):
    weapon, _ = clamp_weapon(
        make_result(
            effects=[("fire_dot", "on_hit", {"dotDamagePerSecond": 999, "durationSeconds": -3})]
        ),
        catalog,
    )

    params = {p.key: p.value for p in weapon.effects[0].params}
    assert params["dotDamagePerSecond"] == 6  # max
    assert params["durationSeconds"] == 2  # min


def test_트리거_파라미터도_함께_채워진다(catalog):
    weapon, _ = clamp_weapon(
        make_result(effects=[("fire_dot", "after_seconds", {"delaySeconds": 2})]), catalog
    )

    params = {p.key: p.value for p in weapon.effects[0].params}
    assert params["delaySeconds"] == 2
    assert "dotDamagePerSecond" in params


def test_빠뜨린_파라미터는_최소값으로_채워진다(catalog):
    weapon, _ = clamp_weapon(make_result(effects=[("pierce", "on_hit", {})]), catalog)

    params = {p.key: p.value for p in weapon.effects[0].params}
    assert params["maxPierceCount"] == 1


# ── 예산 ────────────────────────────────────────────────────────────────


def test_전부_최대로_찍으면_예산_안으로_깎인다(catalog):
    ranged = catalog.category("ranged")
    weapon, report = clamp_weapon(
        make_result(
            stats={s.key: s.max for s in ranged.stats},
            weapon_type="Missile",  # 짝 궤도 homing이 비싼 궤도다
            delivery="homing",
            delivery_params={"turnRateDegPerSecond": 540, "acquireRange": 10},
            effects=[
                ("explosion", "on_hit", {"explosionDamage": 15, "explosionRadius": 4}),
                ("chain", "on_hit", {"maxChains": 5, "chainDamagePercent": 80}),
            ],
        ),
        catalog,
    )

    assert total_of(report) <= report.totalBudget + 0.01
    # 무기 자체는 남아 있어야 한다 — 깎는 것이지 없애는 것이 아니다
    assert weapon.stats_map["damage"] > 0


def test_예산_안이면_손대지_않는다(catalog):
    original = make_result(
        weapon_type="Projectile",  # 투사체=straight 짝을 맞춰야 궤도 교정이 없다
        stats={"damage": 2, "shotsPerSecond": 1, "projectileSpeed": 8, "lifetime": 4},
        effects=[("pierce", "on_hit", {"maxPierceCount": 2})],
    )
    weapon, report = clamp_weapon(original, catalog)

    assert report.clampScale is None
    assert report.dropped == []
    assert weapon.stats_map["damage"] == 2
    assert weapon.delivery.deliveryId == "straight"


def test_성의_보너스는_상한을_넘지_않는다(catalog):
    _, low = clamp_weapon(make_result(effort=0.0), catalog)
    _, high = clamp_weapon(make_result(effort=1.0), catalog)
    _, over = clamp_weapon(make_result(effort=99.0), catalog)

    assert low.effortBonus == 0
    assert high.effortBonus == catalog.budget.effort_bonus_max
    assert over.effortBonus == high.effortBonus


def test_스탯을_최소로_두면_비싼_궤도를_살_수_있다(catalog):
    ranged = catalog.category("ranged")
    weapon, report = clamp_weapon(
        make_result(
            weapon_type="Missile",  # 짝 궤도인 homing이 비싼 궤도다 (비용 12+)
            stats={s.key: s.min for s in ranged.stats},
            delivery="homing",
            delivery_params={"turnRateDegPerSecond": 270, "acquireRange": 6},
        ),
        catalog,
    )

    assert weapon.delivery.deliveryId == "homing"
    assert report.statCost == 0
    assert total_of(report) <= report.totalBudget + 0.01


def test_고정비용만으로_넘치면_효과부터_버린다(catalog):
    ranged = catalog.category("ranged")
    weapon, report = clamp_weapon(
        make_result(
            stats={s.key: s.max for s in ranged.stats},
            weapon_type="Missile",  # 짝 궤도 homing이 비싼 궤도다
            delivery="homing",
            delivery_params={"turnRateDegPerSecond": 540, "acquireRange": 10},
            effects=[
                ("explosion", "on_hit", {"explosionDamage": 15, "explosionRadius": 4}),
                ("chain", "on_hit", {"maxChains": 5}),
                ("fire_dot", "on_hit", {"dotDamagePerSecond": 6}),
            ],
        ),
        catalog,
    )

    assert total_of(report) <= report.totalBudget + 0.01
    assert len(weapon.effects) <= 3


def test_비용이_음수로_내려가지_않는다(catalog):
    """긴 쿨다운은 할인이지 예산 벌이가 아니다."""
    _, report = clamp_weapon(
        make_result(effects=[("pierce", "on_cooldown", {"cooldownSeconds": 12})]), catalog
    )

    assert all(e.cost >= 0 for e in report.effectCosts)
    assert report.totalCost >= 0


# ── DPS 상한 ────────────────────────────────────────────────────────────


def test_DPS_상한을_넘으면_연사_속도가_깎인다(catalog):
    for category_id, weapon_type in (("melee", "Sword"), ("ranged", "Projectile")):
        cat = catalog.category(category_id)
        damage, rate = cat.dps_pair()
        weapon, _ = clamp_weapon(
            make_result(
                category=category_id,
                weapon_type=weapon_type,
                stats={damage.key: damage.max, rate.key: rate.max},
            ),
            catalog,
        )

        stats = weapon.stats_map
        assert stats[damage.key] * stats[rate.key] <= cat.max_dps + 0.01, category_id
        # 한 방의 무게는 무기의 정체성 — damage가 아니라 연사를 깎는다
        assert stats[damage.key] == damage.max, category_id


def test_DPS_상한_안이면_손대지_않는다(catalog):
    weapon, _ = clamp_weapon(
        make_result(
            category="melee",
            weapon_type="Sword",
            stats={"damage": 5, "attacksPerSecond": 0.5},
        ),
        catalog,
    )

    assert weapon.stats_map["damage"] == 5
    assert weapon.stats_map["attacksPerSecond"] == 0.5


def test_상한_판정은_클라이언트가_쓸_반올림_정수_기준이다(catalog):
    """Unity(ForgeDto)가 damage를 정수로 반올림한다 — 서버 숫자로 상한 안이어도
    반올림 후 넘는 조합(3.4×1.2=4.08 → 3×1.2)은 미리 잡아야 한다."""
    weapon, _ = clamp_weapon(
        make_result(
            category="melee",
            weapon_type="Sword",
            stats={"damage": 4.4, "attacksPerSecond": 1.2},
        ),
        catalog,
    )

    stats = weapon.stats_map
    assert stats["damage"] == 4  # 클라이언트와 같은 반올림으로 스냅
    assert 4 * stats["attacksPerSecond"] <= catalog.category("melee").max_dps + 0.01


# ── 폴백과 재검증 ────────────────────────────────────────────────────────


def test_기본_무기는_예산_안에_있다(catalog):
    weapon, report = clamp_weapon(default_forge_result(catalog), catalog)

    assert total_of(report) <= report.totalBudget + 0.01
    assert report.dropped == []
    assert weapon.category == "ranged"


def test_무기고로_들어온_과한_무기도_깎인다(catalog):
    ranged = catalog.category("ranged")
    forged, _ = clamp_weapon(make_result(stats={"damage": 10}), catalog)
    forged.stats = [ParamPair(key=s.key, value=s.max * 10) for s in ranged.stats]

    checked, report = clamp_existing_weapon(forged, catalog)

    for stat in ranged.stats:
        assert checked.stats_map[stat.key] <= stat.max
    assert total_of(report) <= report.totalBudget + 0.01
