"""프롬프트 모음 — 무기용(비전) 1개, 이미지 생성용 2개(살짝 다듬기 / 완전 새로)."""

from __future__ import annotations

import random

from .catalog import CatalogCategory, CatalogEntry, WeaponCatalog, load_catalog
from .examples import sample_delivery, sample_effect_combos


def build_weapon_system_prompt() -> str:
    return "\n".join(
        [
            "너는 아이들이 그린 무기 그림을 보고 게임 성능을 정하는 대장장이다.",
            "고를 수 있는 것은 주어진 카탈로그 안에 전부 있다. 목록에 없는 id를 지어내지 마라.",
            "반드시 JSON 객체 하나만 출력한다. 코드블록·설명·군말을 붙이지 않는다.",
        ]
    )


def _format_params(entry: CatalogEntry) -> str:
    if not entry.params:
        return "      파라미터 없음"
    return "\n".join(
        f"      {p.key}: {p.min:g}~{p.max:g} (단위 {p.step:g}, 스텝당 비용 {p.cost_per_step:g})"
        for p in entry.params
    )


def _format_entry(entry: CatalogEntry) -> str:
    return "\n".join(
        [
            f"    - {entry.id} ({entry.display_name}, 기본 비용 {entry.base_cost:g})",
            f"      {entry.description}",
            _format_params(entry),
        ]
    )


def _format_category(catalog: WeaponCatalog, category: CatalogCategory) -> str:
    stats = "\n".join(
        f"      {s.key}: {s.min:g}~{s.max:g} (최대로 줄 때 비용 {s.weight:g})"
        for s in category.stats
    )
    deliveries = "\n".join(_format_entry(d) for d in catalog.deliveries_for(category.id))
    effects = "\n".join(_format_entry(e) for e in catalog.effects_for(category.id))

    return "\n".join(
        [
            f"### {category.id} ({category.display_name})",
            f"  {category.description}",
            f"  무기 종류(weaponType): {', '.join(category.weapon_types)}",
            "  스탯:",
            stats,
            "  궤도(무기 종류와 1:1로 정해져 있다 — 종류를 고르면 궤도도 따라온다):",
            _pairing_lines(catalog, category),
            deliveries,
            "  효과:",
            effects,
        ]
    )


def _pairing_lines(catalog: WeaponCatalog, category) -> str:
    """무기 종류 ↔ 궤도 짝을 한 줄로. 짝이 아닌 궤도를 골라도 서버가 짝으로 바꾼다."""
    pairs = []
    for weapon_type in category.weapon_types:
        entry = catalog.delivery_for_type(weapon_type)
        if entry is not None:
            pairs.append(f"{weapon_type}={entry.id}")
    return "    짝: " + ", ".join(pairs)


def build_weapon_user_prompt(
    note: str, catalog: WeaponCatalog | None = None, rng: random.Random | None = None
) -> str:
    catalog = catalog or load_catalog()
    rng = rng or random.Random()
    budget = catalog.budget

    note = note.strip()
    if note:
        note_block = (
            f'플레이어가 붙인 추가 설정: "{note}"\n'
            "이 설명을 무기에 반영해라. 다만 설명이 아무리 강력해도 카탈로그와 예산은 지켜야 한다."
        )
    else:
        note_block = "추가 설정은 없다. 그림만 보고 정해라."

    triggers = "\n".join(_format_entry(t) for t in catalog.triggers)
    categories = "\n\n".join(_format_category(catalog, c) for c in catalog.categories)

    example_lines: list[str] = []
    for category in catalog.categories:
        example_lines.append(f"  [{category.id}] 궤도 예: {sample_delivery(catalog, category.id, rng)}")
        for combo in sample_effect_combos(catalog, category.id, 3, rng):
            example_lines.append(f"  [{category.id}] 효과 예: {combo}")

    return "\n".join(
        [
            "첨부한 그림은 플레이어가 직접 그린 무기다. 이 무기의 이름과 성능을 정해라.",
            "",
            note_block,
            "",
            "## 1. 분류를 먼저 고른다",
            "그림이 칼·도끼·창처럼 손에 쥐고 휘두르는 물건이면 melee,",
            "활·총·지팡이·수리검처럼 무언가를 날리는 물건이면 ranged다.",
            "애매하면 그림의 자루 길이와 날의 위치를 보고 판단해라.",
            "분류에 따라 쓸 수 있는 스탯·궤도·효과가 다르다.",
            "",
            "## 2. 카탈로그 (여기 있는 id만 쓸 수 있다)",
            categories,
            "",
            "  트리거(효과가 언제 터지는가):",
            triggers,
            "",
            "## 3. 예산 규칙",
            f"  - 예산은 {budget.weapon_base:g}점. 그림이 정성스러우면 서버가 최대 "
            f"{budget.effort_bonus_max:g}점까지 더 얹는다(effortScore로 신고해라).",
            "  - 스탯 비용 = (값-최소)/(최대-최소) × 그 스탯의 비용. "
            "**모든 스탯을 최대로 주면 그것만으로 예산을 다 쓴다.**",
            "  - 궤도·효과 비용 = 기본 비용 + (파라미터가 최소에서 한 단위 오를 때마다 스텝당 비용).",
            "  - 즉 화려한 궤도나 강한 효과를 원하면 스탯을 깎아야 한다. 그 맞바꿈이 이 무기의 성격이다.",
            f"  - 효과는 최대 {budget.max_effects}개까지.",
            "  - 예산을 넘기면 서버가 깎는다. 깎이면 무기가 밋밋해지니 스스로 맞춰라.",
            "",
            "## 4. 매번 다른 무기가 나와야 한다",
            "아래는 이번 호출에서 카탈로그를 무작위로 뒤섞어 뽑은 참고용 샘플이다.",
            *example_lines,
            "**이 샘플들과 겹치지 않는 조합을 우선해라.**",
            "",
            "## 5. 그림 해석",
            "  - 형태·색·장식에서 궤도와 효과를 끌어내라. "
            "(뾰족하면 관통, 노란색이면 전격, 초록색이면 독 같은 식)",
            "  - **가장 뻔한 해석을 피해라.** 검을 그렸다고 그냥 휘두르기만 주는 것은 실패다. "
            "검기가 날아가는 검(blade_wave), 제자리에서 도는 검(spin)일 수 있고, "
            "활이라고 꼭 직선일 필요도 없다(유도·낙하·강림).",
            "  - 트리거를 섞어라. 전부 on_hit이면 무기가 심심하다 — "
            "시간차(after_seconds)나 자동 발동(on_cooldown)이 개성을 만든다.",
            "  - 이름은 한국어로, 그림을 창의적으로 해석해서 지어라.",
            "  - flavor는 한국어 1~2문장(200자 이내)의 플레이버 텍스트다. "
            "스탯 요약이 아니라 이 무기의 유래·전설·성격을 짓되, 네가 고른 궤도와 효과가 "
            "왜 그렇게 움직이는지 서사에 녹여라. "
            "(예: 부메랑이면 \"주인 곁을 떠나지 못해 몇 번이고 되돌아온다\"처럼)",
            "  - effortScore(0~1): 선의 양, 색 수, 완성도를 보고 그림의 성의를 매겨라.",
            "",
            "## 6. 출력",
            "  - stats는 고른 분류의 스탯 키만 채운다. 다른 분류의 키는 넣지 마라.",
            "  - 파라미터는 {\"key\":\"이름\",\"value\":숫자} 쌍의 배열로 낸다.",
            "  - 궤도에 파라미터가 없으면 빈 배열로 둔다.",
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
    # 0.80으로 뒀더니 단일 피사체 제약이 무너져 한 장에 무기 3개를 그렸다.
    # 0.62면 확실히 달라지면서도 구도는 유지된다.
    2: 0.62,
}

# 실측으로 늘어난 목록이다 — 여러 개를 그리거나 격자로 배치하는 실패가 잦았다.
_IMG2IMG_NEGATIVE = (
    "multiple objects, several weapons, two weapons, three weapons, collage, "
    "grid, tiled, sprite sheet, variations, duplicate, "
    "background scenery, landscape, dark background, black background, "
    "textured background, patterned background, pebbles, stones, bokeh, "
    "gradient background, noise, vignette, paper texture, fabric, "
    "text, letters, watermark, signature, human, hands, frame, border, "
    "drop shadow, blurry, low quality, cropped"
)

_SHARED_SUFFIX = (
    "exactly one single weapon, centered, "
    "isolated on a completely flat solid pure white background, no background detail"
)

_IMG2IMG_PROMPT = {
    1: (
        "the same hand-drawn weapon, cleaned up line art, tidy smooth outlines, "
        "flat even coloring, crayon and pencil texture kept, childlike drawing style, "
        f"{_SHARED_SUFFIX}"
    ),
    2: (
        "polished 2d game weapon icon, same silhouette and same main colors as the sketch, "
        "detailed shading, metallic highlights, crisp clean edges, vibrant, high quality, "
        f"{_SHARED_SUFFIX}"
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
