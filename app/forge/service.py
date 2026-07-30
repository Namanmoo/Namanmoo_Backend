"""forge 오케스트레이션.

스탯은 항상 뽑고, 이미지는 요청한 단계에서만 만든다.
0단계는 이미지 생성 호출이 아예 없다 — 클라이언트가 그린 그림을 그대로 쓴다.

AIGame pipeline.ts의 사상을 따른다: 무엇이 실패해도 게임은 진행된다.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Protocol

from ..config import ServerConfig
from ..gemini import client as gemini
from ..cloudflare import client as cloudflare_images
from ..openai_api import client as openai_images
from ..gemini.mock import mock_image, mock_seed, mock_stats
from .clamp import clamp_stats
from .prompt import (
    build_img2img_prompt,
    build_refine_prompt,
    build_stats_system_prompt,
    build_stats_user_prompt,
    build_upgrade_prompt,
)
from .schema import (
    ForgeLlmResult,
    ForgeResponse,
    default_forge_result,
    stats_response_schema,
)

STATS_MAX_ATTEMPTS = 3

Logger = Callable[[str], None]


class ForgeEngine(Protocol):
    """테스트에서 갈아끼울 수 있게 좁게 정의한 엔진 인터페이스."""

    name: str

    async def stats(self, png: bytes, note: str) -> Any: ...

    async def image(self, png: bytes, note: str, stage: int) -> str: ...


class MockEngine:
    name = "mock"

    async def stats(self, png: bytes, note: str) -> Any:
        return mock_stats(png, note).model_dump()

    async def image(self, png: bytes, note: str, stage: int) -> str:
        return mock_image(png, stage, mock_seed(png, note))


class LiveEngine:
    """스탯은 Gemini, 이미지는 OpenAI.

    제공자를 나눈 이유는 실측 때문이다 — Gemini 스탯은 무료 티어에서 잘 돌지만
    Gemini 이미지 모델은 무료 할당이 0이었다. 한쪽 키만 있으면 그쪽만 동작하고
    없는 쪽은 예외를 던져 상위에서 폴백으로 처리된다.
    """

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._stats_opts = (
            gemini.GeminiCallOptions(
                api_key=config.gemini_api_key,
                model=config.stats_model,
                timeout_s=config.timeout_s,
            )
            if config.has_stats_provider
            else None
        )
        provider = config.image_provider
        self._image_provider = provider

        if provider == "cloudflare":
            self._image_opts: Any = cloudflare_images.CloudflareImageOptions(
                account_id=config.cloudflare_account_id,
                api_token=config.cloudflare_api_token,
                model=config.cloudflare_image_model,
                timeout_s=config.timeout_s,
            )
        elif provider == "openai":
            self._image_opts = openai_images.OpenAIImageOptions(
                api_key=config.openai_api_key,
                model=config.openai_image_model,
                timeout_s=config.timeout_s,
            )
        else:
            self._image_opts = None

    @property
    def name(self) -> str:
        stats = "gemini" if self._stats_opts else "none"
        return f"stats={stats},image={self._image_provider or 'none'}"

    async def stats(self, png: bytes, note: str) -> Any:
        if self._stats_opts is None:
            raise RuntimeError("GEMINI_API_KEY가 없어 스탯을 만들 수 없습니다.")

        return await gemini.generate_json(
            self._stats_opts,
            image_png=png,
            system=build_stats_system_prompt(),
            prompt=build_stats_user_prompt(note),
            response_schema=stats_response_schema(),
        )

    async def image(self, png: bytes, note: str, stage: int) -> str:
        if self._image_opts is None:
            raise RuntimeError(
                "이미지 제공자 자격증명이 없습니다 "
                "(CLOUDFLARE_ACCOUNT_ID+CLOUDFLARE_API_TOKEN 또는 OPENAI_API_KEY)."
            )

        if self._image_provider == "cloudflare":
            # 단계 구분을 strength로 강제한다 — 프롬프트로 부탁하는 것보다 확실하다
            prompt, negative, strength = build_img2img_prompt(stage)
            return await cloudflare_images.generate_image_edit(
                self._image_opts,
                image_png=png,
                prompt=prompt,
                negative_prompt=negative,
                strength=strength,
            )

        # OpenAI는 strength가 없어 프롬프트로만 단계를 구분한다
        prompt = build_refine_prompt() if stage == 1 else build_upgrade_prompt(note)
        return await openai_images.generate_image_edit(
            self._image_opts, image_png=png, prompt=prompt
        )


def create_engine(config: ServerConfig) -> ForgeEngine:
    if config.use_mock:
        return MockEngine()
    return LiveEngine(config)


async def _resolve_stats(
    engine: ForgeEngine, png: bytes, note: str, log: Logger
) -> tuple[ForgeLlmResult, bool]:
    for attempt in range(1, STATS_MAX_ATTEMPTS + 1):
        try:
            raw = await engine.stats(png, note)
            return ForgeLlmResult.model_validate(raw), False
        except Exception as err:  # 스키마 위반과 호출 실패를 같이 처리한다
            log(f"스탯 실패 ({attempt}/{STATS_MAX_ATTEMPTS}) — {err}")
    return default_forge_result(), True


async def _resolve_image(
    engine: ForgeEngine, png: bytes, note: str, stage: int, log: Logger
) -> tuple[str, bool]:
    """(base64 이미지, 실패했는가). 0단계는 생성하지 않으므로 ("", False)."""
    if stage == 0:
        return "", False

    try:
        return await engine.image(png, note, stage), False
    except Exception as err:
        log(f"{stage}단계 이미지 생성 실패 — {err}")
        # 실패해도 클라이언트는 원본 그림으로 대체한다
        return "", True


async def run_forge(
    engine: ForgeEngine,
    *,
    drawing: bytes,
    note: str,
    stage: int = 0,
    log: Logger = lambda _message: None,
) -> ForgeResponse:
    # 스탯과 이미지를 동시에 — 순차로 하면 대기 시간이 그대로 더해진다
    stats_outcome, image_outcome = await asyncio.gather(
        _resolve_stats(engine, drawing, note, log),
        _resolve_image(engine, drawing, note, stage, log),
    )
    llm_result, fallback = stats_outcome
    image, image_failed = image_outcome
    stats, report = clamp_stats(llm_result.stats)

    return ForgeResponse(
        name=llm_result.name,
        flavor=llm_result.flavor,
        stats=stats,
        stage=stage,
        image=image,
        imageFailed=image_failed,
        source=engine.name,
        fallback=fallback,
        clamp=report,
    )
