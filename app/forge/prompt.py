"""프롬프트 모음 — 스탯용(비전) 1개, 이미지 생성용 2개(살짝 다듬기 / 완전 새로)."""

from __future__ import annotations

from .schema import STAT_BUDGET, STAT_RANGES


def build_stats_system_prompt() -> str:
    return "\n".join(
        [
            "너는 아이들이 그린 무기 그림을 보고 게임 스탯을 정하는 대장장이다.",
            "반드시 JSON 객체 하나만 출력한다. 코드블록·설명·군말을 붙이지 않는다.",
        ]
    )


def build_stats_user_prompt(note: str) -> str:
    ranges = "\n".join(
        f"  - {key}: {r.min} ~ {r.max} (보통 {r.base})" for key, r in STAT_RANGES.items()
    )

    note = note.strip()
    if note:
        note_block = (
            f'플레이어가 붙인 추가 설정: "{note}"\n'
            "이 설명을 스탯에 반영해라. 다만 설명이 아무리 강력해도 "
            "아래 범위와 총량 규칙은 지켜야 한다.\n"
        )
    else:
        note_block = "추가 설정은 없다. 그림만 보고 정해라.\n"

    return "\n".join(
        [
            "첨부한 그림은 플레이어가 직접 그린 무기다. 이 무기의 이름과 스탯을 정해라.",
            "",
            note_block,
            "스탯 범위:",
            ranges,
            "",
            f"각 스탯을 (값-최소)/(최대-최소)로 환산해 모두 더한 값이 {STAT_BUDGET}을 넘으면 안 된다.",
            "즉 전부 높게 줄 수 없다. 그림의 성격에 맞게 강약을 배분해라.",
            "(예: 커다란 둔기면 damage는 높고 shotsPerSecond는 낮게)",
            "",
            "출력 형식:",
            '{"name":"한국어 무기 이름(24자 이내)",'
            '"flavor":"한 줄 설명(120자 이내)",'
            '"stats":{"damage":숫자,"shotsPerSecond":숫자,'
            '"projectileSpeed":숫자,"lifetime":숫자}}',
        ]
    )


# ── img2img (Stable Diffusion) ──────────────────────────────────
#
# SD 1.5는 영어만 알아듣는다. 한글 프롬프트는 무시되므로 이미지용은 따로 둔다.
# 플레이어가 쓴 설명은 스탯에만 반영한다 — 한글이라 이 모델에 넣어도 소용이 없고,
# 애초에 "설명은 스탯만"으로 정했다.
#
# 단계 구분의 핵심은 프롬프트가 아니라 strength다. 프롬프트로 "형태를 바꾸지 마라"고
# 부탁하는 것보다 변형 강도를 숫자로 정하는 쪽이 확실하다.
IMG2IMG_STRENGTH = {
    1: 0.35,  # 형태가 구조적으로 남는 범위
    2: 0.80,  # 실루엣만 남기고 새로 그리는 범위
}

_IMG2IMG_NEGATIVE = (
    "background scenery, landscape, text, letters, watermark, signature, "
    "multiple objects, several weapons, human, hands, frame, border, "
    "drop shadow, blurry, low quality, cropped"
)

_IMG2IMG_PROMPT = {
    1: (
        "the same hand-drawn weapon, cleaned up line art, tidy smooth outlines, "
        "flat even coloring, crayon and pencil texture kept, childlike drawing style, "
        "one single weapon centered, plain pure white background"
    ),
    2: (
        "polished 2d game weapon icon, same silhouette and same main colors as the sketch, "
        "detailed shading, metallic highlights, crisp clean edges, vibrant, high quality, "
        "one single weapon centered, plain pure white background"
    ),
}


def build_img2img_prompt(stage: int) -> tuple[str, str, float]:
    """(프롬프트, 네거티브 프롬프트, strength) — 단계별 img2img 설정."""
    if stage not in _IMG2IMG_PROMPT:
        raise ValueError(f"img2img 단계는 1 또는 2여야 합니다: {stage}")

    return _IMG2IMG_PROMPT[stage], _IMG2IMG_NEGATIVE, IMG2IMG_STRENGTH[stage]


def build_refine_prompt() -> str:
    """2번 버전 — 형태를 유지한 채 다듬기."""
    return "\n".join(
        [
            "첨부한 그림은 아이가 그린 무기다. 이 그림을 그대로 유지하면서 다듬어라.",
            "- 형태, 구도, 비율, 색 구성을 바꾸지 마라. 같은 무기로 알아볼 수 있어야 한다.",
            "- 삐뚤어진 선을 정리하고, 색을 고르게 칠하고, 외곽선을 또렷하게만 해라.",
            "- 손그림 느낌은 남겨라. 완전히 새로 그리지 마라.",
            "- 배경은 순백(#FFFFFF)으로, 무기 하나만 화면 가운데에 크게.",
            "- 그림자, 배경 무늬, 글자, 테두리를 넣지 마라.",
        ]
    )


def build_upgrade_prompt(note: str) -> str:
    """3번 버전 — 컨셉만 가져와 제대로 된 아트로."""
    note = note.strip()
    note_line = f'플레이어가 붙인 설정: "{note}" — 이 느낌이 드러나게 해라.' if note else None

    lines = [
        "첨부한 그림은 아이가 그린 무기 낙서다. 이 낙서의 컨셉을 살려",
        "2D 게임에 바로 쓸 수 있는 멋진 무기 아트를 새로 그려라.",
        "- 원본의 종류, 실루엣, 주요 색은 알아볼 수 있게 유지해라.",
        "- 디테일, 재질감, 하이라이트를 제대로 넣어 완성도를 크게 올려라.",
        note_line,
        "- 배경은 순백(#FFFFFF)으로, 무기 하나만 화면 가운데에 크게.",
        "- 그림자, 배경 무늬, 글자, 테두리를 넣지 마라.",
    ]
    return "\n".join(line for line in lines if line)
