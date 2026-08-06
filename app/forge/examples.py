"""프롬프트에 넣을 무작위 조합 예시 생성기 (순수 함수 — 테스트 대상).

같은 그림을 여러 번 넣어도 다른 무기가 나와야 한다. 예시를 몇 개로 고정해 두면
모델이 거기에 달라붙어 매번 같은 조합을 내놓는다 — 그래서 호출마다 카탈로그에서
새로 뽑고, "이것들과 겹치지 않게" 지시한다.
"""

from __future__ import annotations

import random

from .catalog import CatalogEntry, WeaponCatalog


def _random_param_value(param, rng: random.Random) -> float:
    steps = max(0, round((param.max - param.min) / param.step))
    return round(param.min + rng.randint(0, steps) * param.step, 3)


def _format_params(entry: CatalogEntry, params: dict[str, float]) -> str:
    if not params:
        return ""
    body = ", ".join(f"{k}={v:g}" for k, v in params.items())
    return f" ({body})"


def sample_delivery(
    catalog: WeaponCatalog, category: str, rng: random.Random | None = None
) -> str:
    rng = rng or random.Random()
    options = catalog.deliveries_for(category)
    entry = rng.choice(list(options))
    params = {p.key: _random_param_value(p, rng) for p in entry.params}
    return f"{entry.id}{_format_params(entry, params)}"


def sample_effect_pairs(
    catalog: WeaponCatalog, category: str, count: int, rng: random.Random | None = None
) -> list[tuple[CatalogEntry, CatalogEntry, dict[str, float]]]:
    """서로 다른 (효과, 트리거, 파라미터) 조합을 count개까지 뽑는다."""
    rng = rng or random.Random()
    effects = list(catalog.effects_for(category))
    triggers = list(catalog.triggers)
    if not effects or not triggers:
        return []

    pairs = [(e, t) for e in effects for t in triggers]
    rng.shuffle(pairs)

    sampled: list[tuple[CatalogEntry, CatalogEntry, dict[str, float]]] = []
    for effect, trigger in pairs[:count]:
        params: dict[str, float] = {}
        for source in (trigger, effect):
            for p in source.params:
                params[p.key] = _random_param_value(p, rng)
        sampled.append((effect, trigger, params))
    return sampled


def sample_effect_combos(
    catalog: WeaponCatalog, category: str, count: int, rng: random.Random | None = None
) -> list[str]:
    """프롬프트에 그대로 넣을 사람이 읽는 형태."""
    return [
        f"{effect.id} @ {trigger.id}{_format_params(effect, params)}"
        for effect, trigger, params in sample_effect_pairs(catalog, category, count, rng)
    ]
