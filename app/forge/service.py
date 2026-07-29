"""forge 오케스트레이션 — 스탯 1회 + 이미지 2회를 병렬로 돌리고 결과를 합친다.

AIGame pipeline.ts의 사상을 따른다: 무엇이 실패해도 게임은 진행된다.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Protocol

from ..config import ServerConfig
from ..gemini import client as gemini
from ..gemini.mock import mock_image, mock_seed, mock_stats
from .clamp import clamp_stats
from .prompt import (
    build_refine_prompt,
    build_stats_system_prompt,
    build_stats_user_prompt,
    build_upgrade_prompt,
)
from .schema import (
    ForgeLlmResult,
    ForgeResponse,
    ForgeVariant,
    default_forge_result,
)

STATS_MAX_ATTEMPTS = 3

Logger = Callable[[str], None]


class ForgeEngine(Protocol):
    """테스트에서 갈아끼울 수 있게 좁게 정의한 엔진 인터페이스."""

    name: str

    async def stats(self, png: bytes, note: str) -> Any: ...

    async def image(self, png: bytes, note: str, version: int) -> str: ...


class MockEngine:
    name = "mock"

    async def stats(self, png: bytes, note: str) -> Any:
        return mock_stats(png, note).model_dump()

    async def image(self, png: bytes, note: str, version: int) -> str:
        return mock_image(png, version, mock_seed(png, note))


class GeminiEngine:
    name = "gemini"

    def __init__(self, config: ServerConfig) -> None:
        assert config.gemini_api_key is not None
        self._stats_opts = gemini.GeminiCallOptions(
            api_key=config.gemini_api_key,
            model=config.stats_model,
            timeout_s=config.timeout_s,
        )
        self._image_opts = gemini.GeminiCallOptions(
            api_key=config.gemini_api_key,
            model=config.image_model,
            timeout_s=config.timeout_s,
        )

    async def stats(self, png: bytes, note: str) -> Any:
        return await gemini.generate_json(
            self._stats_opts,
            image_png=png,
            system=build_stats_system_prompt(),
            prompt=build_stats_user_prompt(note),
        )

    async def image(self, png: bytes, note: str, version: int) -> str:
        prompt = build_refine_prompt() if version == 2 else build_upgrade_prompt(note)
        return await gemini.generate_image(self._image_opts, image_png=png, prompt=prompt)


def create_engine(config: ServerConfig) -> ForgeEngine:
    if config.use_mock or config.gemini_api_key is None:
        return MockEngine()
    return GeminiEngine(config)


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
    engine: ForgeEngine, png: bytes, note: str, version: int, log: Logger
) -> ForgeVariant:
    try:
        image = await engine.image(png, note, version)
        return ForgeVariant(version=version, image=image, failed=False)
    except Exception as err:
        log(f"{version}번 이미지 생성 실패 — {err}")
        # 실패해도 클라이언트는 원본 그림으로 그 칸을 채운다
        return ForgeVariant(version=version, image="", failed=True)


async def run_forge(
    engine: ForgeEngine,
    *,
    drawing: bytes,
    note: str,
    log: Logger = lambda _message: None,
) -> ForgeResponse:
    # 스탯과 이미지 두 장을 동시에 — 순차로 하면 대기 시간이 그대로 더해진다
    stats_outcome, refined, upgraded = await asyncio.gather(
        _resolve_stats(engine, drawing, note, log),
        _resolve_image(engine, drawing, note, 2, log),
        _resolve_image(engine, drawing, note, 3, log),
    )
    llm_result, fallback = stats_outcome
    stats, report = clamp_stats(llm_result.stats)

    return ForgeResponse(
        name=llm_result.name,
        flavor=llm_result.flavor,
        stats=stats,
        variants=[
            ForgeVariant(version=1, image="", failed=False),
            refined,
            upgraded,
        ],
        source=engine.name,
        fallback=fallback,
        clamp=report,
    )
