"""목 구현 — GEMINI_API_KEY 없이도 /forge 전 흐름이 돌게 한다.

Unity 쪽 3버전 선택 UI를 키 없이 끝까지 검증하는 게 목적이라,
버전마다 눈에 띄게 다르면서도 원본 그림과 관계가 보이는 이미지를 돌려준다.
(원본을 실제로 가공하므로 "그림이 반영되는가"까지 확인할 수 있다.)
"""

from __future__ import annotations

import base64
import io
import os
import random

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ..forge.catalog import load_catalog
from ..forge.examples import sample_effect_pairs
from ..forge.schema import ForgeDelivery, ForgeEffectEntry, ForgeLlmResult, ParamPair

_PREFIX = ("삐뚤빼뚤", "낙서", "크레용", "스케치", "연필심", "색종이")
_NOUN = ("대검", "광선총", "망치", "창", "지팡이", "단검")


def mock_seed(png: bytes, note: str) -> int:
    """그림 바이트에서 뽑은 결정적 시드 — 같은 그림이면 같은 결과가 나온다.

    간격을 크기에 맞춰 잡는다. 997로 고정하면 작은 PNG는 첫 바이트(항상 0x89)
    하나만 보게 되어 어떤 그림을 넣어도 같은 무기가 나온다.
    """
    stride = max(1, len(png) // 512)
    h = 2166136261
    for i in range(0, len(png), stride):
        h = ((h ^ png[i]) * 16777619) & 0xFFFFFFFF
    for ch in note:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _requested_delivery(catalog, note: str):
    """메모(또는 FORGE_FORCE_DELIVERY 환경변수)에서 궤도 지명을 찾는다.

    목 모드 전용 개발 편의다. 원하는 궤도가 나올 때까지 다시 그리는 대신
    추가 설정에 궤도 이름("검기"든 "blade_wave"든)을 적으면 그 궤도가 나온다.
    자동화 테스트처럼 입력칸을 못 쓰는 곳은 환경변수로 강제한다:
    FORGE_FORCE_DELIVERY=blade_wave ./run.sh
    """
    for delivery in catalog.deliveries:
        if delivery.id in note or delivery.display_name in note:
            return delivery

    forced = os.environ.get("FORGE_FORCE_DELIVERY", "").strip()
    return catalog.delivery(forced) if forced else None


def _requested_effect(catalog, note: str):
    """메모(또는 FORGE_FORCE_EFFECT 환경변수)에서 효과 지명을 찾는다.

    "검기"나 "화염"처럼 효과 이름을 적으면 그 효과가 반드시 붙는다.
    """
    for effect in catalog.effects:
        if effect.id in note or effect.display_name in note:
            return effect

    forced = os.environ.get("FORGE_FORCE_EFFECT", "").strip()
    return catalog.effect(forced) if forced else None


def _trigger_for(effect_id: str) -> str:
    """지명된 효과에 어울리는 트리거 — 검기는 맞아야가 아니라 공격마다 나간다."""
    return "on_attack" if effect_id == "blade_wave" else "on_hit"


def mock_stats(png: bytes, note: str) -> ForgeLlmResult:
    """카탈로그에서 실제로 유효한 무기를 결정적으로 뽑는다.

    키 없이도 3축(분류·궤도·효과)이 끝까지 흐르는지 보는 게 목적이라,
    스탯만 채우고 마는 대신 궤도와 효과까지 고른다.
    """
    seed = mock_seed(png, note)
    catalog = load_catalog()
    rng = random.Random(seed)

    def t(offset: int) -> float:
        return ((seed >> offset) & 0xFF) / 255

    requested = _requested_delivery(catalog, note)
    wanted_effect = _requested_effect(catalog, note)

    # 지명이 있으면 그것이 허용되는 분류로 맞춘다 — 검기를 시켰는데
    # 검기가 못 붙는 분류가 나오면 지명이 조용히 증발한다.
    if requested is not None:
        allowed = [c for c in catalog.categories if requested.allows(c.id)]
    elif wanted_effect is not None:
        allowed = [c for c in catalog.categories if wanted_effect.allows(c.id)]
    else:
        allowed = list(catalog.categories)

    category = allowed[seed % len(allowed)]

    if requested is not None and requested.allows(category.id):
        delivery = requested
    else:
        deliveries = catalog.deliveries_for(category.id)
        delivery = deliveries[(seed >> 5) % len(deliveries)]

    # 스탯은 범위의 20~55% 사이 — 궤도·효과를 붙일 예산을 남긴다
    stats = [
        ParamPair(key=s.key, value=round(s.denormalize(0.2 + 0.35 * t(8 * i)), 2))
        for i, s in enumerate(category.stats)
    ]

    if wanted_effect is not None and wanted_effect.allows(category.id):
        effects = [
            ForgeEffectEntry(
                effectId=wanted_effect.id,
                triggerId=_trigger_for(wanted_effect.id),
                params=[],
            )
        ]
    else:
        effects = [
            ForgeEffectEntry(
                effectId=effect.id,
                triggerId=trigger.id,
                params=[ParamPair(key=k, value=v) for k, v in params.items()],
            )
            for effect, trigger, params in sample_effect_pairs(catalog, category.id, 1, rng)
        ]

    note = note.strip()
    return ForgeLlmResult(
        name=f"{_PREFIX[seed % len(_PREFIX)]} {_NOUN[(seed >> 3) % len(_NOUN)]}",
        flavor=(
            f'"{note[:40]}" 라고 적힌 종이가 손잡이에 붙어 있다.'
            if note
            else "종이 냄새가 나는 무기다."
        ),
        category=category.id,
        weaponType=category.weapon_types[(seed >> 11) % len(category.weapon_types)],
        stats=stats,
        delivery=ForgeDelivery(deliveryId=delivery.id, params=[]),
        effects=effects,
        effortScore=round(t(16), 2),
    )


def _flatten_to_white(image: Image.Image) -> Image.Image:
    """투명 배경을 흰색으로 — 실제 생성 프롬프트도 흰 배경을 요구하므로 조건을 맞춘다."""
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, rgba).convert("RGB")


def _fallback_shape(stage: int, seed: int, size: int = 512) -> Image.Image:
    """원본을 열 수 없을 때 쓰는 단순 도형."""
    from PIL import ImageDraw

    image = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    hue = (seed >> (stage * 4)) % 360
    color = tuple(
        int(c * 255)
        for c in __import__("colorsys").hsv_to_rgb(hue / 360, 0.65, 0.9)
    )
    draw.rectangle((size * 0.12, size * 0.42, size * 0.7, size * 0.58), fill=color)
    draw.polygon(
        [
            (size * 0.7, size * 0.38),
            (size * 0.7, size * 0.62),
            (size * 0.92, size * 0.5),
        ],
        fill=color,
    )
    return image


def mock_image(png: bytes, stage: int, seed: int) -> str:
    """원본을 가공해 단계별로 다른 이미지를 만든다. 반환값은 base64 PNG."""
    try:
        source = _flatten_to_white(Image.open(io.BytesIO(png)))
    except Exception:
        source = _fallback_shape(stage, seed)

    if stage == 1:
        # 살짝 다듬기 — 부드럽게 + 대비를 올려 선이 또렷해 보이게
        out = source.filter(ImageFilter.SMOOTH_MORE)
        out = ImageEnhance.Contrast(out).enhance(1.35)
        out = ImageEnhance.Color(out).enhance(1.2)
    else:
        # 완전 새로 — 색을 뭉개고 톤을 크게 바꿔 한눈에 다른 그림으로 보이게
        out = source.filter(ImageFilter.GaussianBlur(radius=1.2))
        out = ImageOps.posterize(out, 3)
        out = ImageEnhance.Color(out).enhance(1.9)
        out = ImageEnhance.Brightness(out).enhance(1.05)

    buffer = io.BytesIO()
    out.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
