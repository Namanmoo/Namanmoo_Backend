"""제공자 선택 — 스탯은 Gemini, 이미지는 Cloudflare 또는 OpenAI.

Gemini 이미지 모델은 무료 티어 할당이 0이라(실측) 쓸 수 없었고, OpenAI는 크레딧이
있어야 한다. 그래서 자격증명이 한쪽만 있는 상태가 정상 운영 상태다 — 그 경우
어떻게 동작하는지 고정해 둔다.
"""

from __future__ import annotations

import pytest

from app.config import load_config
from app.forge.service import LiveEngine, MockEngine, create_engine

from .conftest import make_config


def live(**overrides) -> LiveEngine:
    return LiveEngine(make_config(use_mock=False, **overrides))


def test_no_credentials_falls_back_to_mock():
    cfg = load_config({})

    assert cfg.use_mock is True
    assert cfg.image_provider is None
    assert isinstance(create_engine(cfg), MockEngine)


def test_any_credential_leaves_mock_mode():
    assert load_config({"GEMINI_API_KEY": "g"}).use_mock is False
    assert load_config({"OPENAI_API_KEY": "o"}).use_mock is False
    assert load_config(
        {"CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t"}
    ).use_mock is False


def test_half_configured_cloudflare_does_not_count():
    # 계정 ID만 있고 토큰이 없으면 호출이 불가능하다
    cfg = load_config({"CLOUDFLARE_ACCOUNT_ID": "a"})

    assert cfg.use_mock is True
    assert cfg.image_provider is None


def test_forge_mode_mock_overrides_present_credentials():
    cfg = load_config(
        {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o", "FORGE_MODE": "mock"}
    )

    assert cfg.use_mock is True
    assert cfg.has_stats_provider is False
    assert cfg.image_provider is None


def test_cloudflare_wins_when_both_are_configured():
    # Cloudflare는 무료 할당이 있고 strength로 단계를 제어할 수 있어 먼저 쓴다
    cfg = load_config(
        {
            "OPENAI_API_KEY": "o",
            "CLOUDFLARE_ACCOUNT_ID": "a",
            "CLOUDFLARE_API_TOKEN": "t",
        }
    )

    assert cfg.image_provider == "cloudflare"
    assert cfg.image_model == "@cf/runwayml/stable-diffusion-v1-5-img2img"


def test_provider_override_forces_openai():
    cfg = load_config(
        {
            "OPENAI_API_KEY": "o",
            "CLOUDFLARE_ACCOUNT_ID": "a",
            "CLOUDFLARE_API_TOKEN": "t",
            "IMAGE_PROVIDER": "openai",
        }
    )

    assert cfg.image_provider == "openai"
    assert cfg.image_model == "gpt-image-1.5"


def test_override_to_a_provider_without_credentials_yields_none():
    cfg = load_config({"OPENAI_API_KEY": "o", "IMAGE_PROVIDER": "cloudflare"})

    assert cfg.image_provider is None


def test_unknown_override_is_rejected_at_startup():
    with pytest.raises(ValueError, match="IMAGE_PROVIDER"):
        load_config({"IMAGE_PROVIDER": "midjourney"})


def test_source_name_reports_which_providers_are_live():
    both = live(gemini_api_key="g", cloudflare_account_id="a", cloudflare_api_token="t")
    stats_only = live(gemini_api_key="g")
    image_only = live(openai_api_key="o")

    assert both.name == "stats=gemini,image=cloudflare"
    assert stats_only.name == "stats=gemini,image=none"
    assert image_only.name == "stats=none,image=openai"


@pytest.mark.asyncio
async def test_missing_image_credentials_raise_so_the_caller_can_fall_back():
    engine = live(gemini_api_key="g")

    with pytest.raises(RuntimeError, match="이미지 제공자"):
        await engine.image(b"png", "", 1)


@pytest.mark.asyncio
async def test_missing_stats_key_raises_so_the_caller_can_fall_back():
    engine = live(openai_api_key="o")

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await engine.stats(b"png", "")


def test_image_models_come_from_their_own_env_vars():
    openai_cfg = load_config(
        {"OPENAI_API_KEY": "o", "OPENAI_IMAGE_MODEL": "gpt-image-2"}
    )
    cf_cfg = load_config(
        {
            "CLOUDFLARE_ACCOUNT_ID": "a",
            "CLOUDFLARE_API_TOKEN": "t",
            "CLOUDFLARE_IMAGE_MODEL": "@cf/black-forest-labs/flux-1-schnell",
        }
    )

    assert openai_cfg.image_model == "gpt-image-2"
    assert cf_cfg.image_model == "@cf/black-forest-labs/flux-1-schnell"
