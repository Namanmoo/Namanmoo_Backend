"""목 구현 — GEMINI_API_KEY 없이도 /forge 전 흐름이 돌게 한다.

Unity 쪽 3버전 선택 UI를 키 없이 끝까지 검증하는 게 목적이라,
버전마다 눈에 띄게 다르면서도 원본 그림과 관계가 보이는 이미지를 돌려준다.
(원본을 실제로 가공하므로 "그림이 반영되는가"까지 확인할 수 있다.)
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ..forge.schema import STAT_RANGES, ForgeLlmResult, ForgeStats

_PREFIX = ("삐뚤빼뚤", "낙서", "크레용", "스케치", "연필심", "색종이")
_NOUN = ("대검", "광선총", "망치", "창", "지팡이", "단검")


def mock_seed(png: bytes, note: str) -> int:
    """그림 바이트에서 뽑은 결정적 시드 — 같은 그림이면 같은 결과가 나온다."""
    h = 2166136261
    for i in range(0, len(png), 997):
        h = ((h ^ png[i]) * 16777619) & 0xFFFFFFFF
    for ch in note:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def mock_stats(png: bytes, note: str) -> ForgeLlmResult:
    seed = mock_seed(png, note)

    def t(offset: int) -> float:
        return ((seed >> offset) & 0xFF) / 255

    def scaled(key: str, ratio: float) -> float:
        r = STAT_RANGES[key]
        return r.min + ratio * (r.max - r.min)

    note = note.strip()
    return ForgeLlmResult(
        name=f"{_PREFIX[seed % len(_PREFIX)]} {_NOUN[(seed >> 3) % len(_NOUN)]}",
        flavor=(
            f'"{note[:40]}" 라고 적힌 종이가 손잡이에 붙어 있다.'
            if note
            else "종이 냄새가 나는 무기다."
        ),
        stats=ForgeStats(
            damage=scaled("damage", t(0)),
            shotsPerSecond=scaled("shotsPerSecond", t(8)),
            projectileSpeed=scaled("projectileSpeed", t(16)),
            lifetime=scaled("lifetime", t(24)),
        ),
    )


def _flatten_to_white(image: Image.Image) -> Image.Image:
    """투명 배경을 흰색으로 — 실제 생성 프롬프트도 흰 배경을 요구하므로 조건을 맞춘다."""
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, rgba).convert("RGB")


def _fallback_shape(version: int, seed: int, size: int = 512) -> Image.Image:
    """원본을 열 수 없을 때 쓰는 단순 도형."""
    from PIL import ImageDraw

    image = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    hue = (seed >> (version * 4)) % 360
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


def mock_image(png: bytes, version: int, seed: int) -> str:
    """원본을 가공해 버전별로 다른 이미지를 만든다. 반환값은 base64 PNG."""
    try:
        source = _flatten_to_white(Image.open(io.BytesIO(png)))
    except Exception:
        source = _fallback_shape(version, seed)

    if version == 2:
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
