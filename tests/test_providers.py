"""제공자 분리 — 스탯은 Gemini, 이미지는 OpenAI.

Gemini 이미지 모델은 무료 티어 할당이 0이라(실측) 쓸 수 없었다.
그래서 한쪽 키만 있는 상태가 정상 운영 상태다 — 그 경우 동작을 고정해 둔다.
"""

from __future__ import annotations

import pytest

from app.config import ServerConfig, load_config
from app.forge.service import LiveEngine, MockEngine, create_engine


def config(**overrides) -> ServerConfig:
    base = dict(
        port=8790,
        host="127.0.0.1",
        gemini_api_key=None,
        openai_api_key=None,
        stats_model="gemini-flash-latest",
        image_model="gpt-image-1.5",
        use_mock=False,
        timeout_s=5,
    )
    base.update(overrides)
    return ServerConfig(**base)


def test_no_keys_falls_back_to_mock():
    cfg = load_config({})

    assert cfg.use_mock is True
    assert isinstance(create_engine(cfg), MockEngine)


def test_either_key_alone_leaves_mock_mode():
    assert load_config({"GEMINI_API_KEY": "g"}).use_mock is False
    assert load_config({"OPENAI_API_KEY": "o"}).use_mock is False


def test_forge_mode_mock_overrides_present_keys():
    cfg = load_config({"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o", "FORGE_MODE": "mock"})

    assert cfg.use_mock is True
    assert cfg.has_stats_provider is False
    assert cfg.has_image_provider is False


def test_source_name_reports_which_provider_is_live():
    both = LiveEngine(config(gemini_api_key="g", openai_api_key="o"))
    stats_only = LiveEngine(config(gemini_api_key="g"))
    image_only = LiveEngine(config(openai_api_key="o"))

    assert both.name == "stats=gemini,image=openai"
    assert stats_only.name == "stats=gemini,image=none"
    assert image_only.name == "stats=none,image=openai"


@pytest.mark.asyncio
async def test_missing_image_key_raises_so_the_caller_can_fall_back():
    engine = LiveEngine(config(gemini_api_key="g"))

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await engine.image(b"png", "", 1)


@pytest.mark.asyncio
async def test_missing_stats_key_raises_so_the_caller_can_fall_back():
    engine = LiveEngine(config(openai_api_key="o"))

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await engine.stats(b"png", "")


def test_image_model_comes_from_openai_env_var():
    # 이미지 제공자가 Gemini에서 OpenAI로 바뀌었으므로 env 이름도 따라간다
    cfg = load_config({"OPENAI_API_KEY": "o", "OPENAI_IMAGE_MODEL": "gpt-image-2"})

    assert cfg.image_model == "gpt-image-2"
