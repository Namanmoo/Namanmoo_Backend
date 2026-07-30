"""서버 설정 — 환경변수 로드.

GEMINI_API_KEY가 없으면 목 모드로 뜬다. 목 모드에서도 /forge 응답 형태는 같아서
Unity 쪽 3버전 선택 흐름을 키 없이 끝까지 검증할 수 있다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """스탯과 이미지는 서로 다른 제공자를 쓴다.

    스탯은 Gemini 무료 티어에서 잘 돌아가지만, Gemini 이미지 모델은 무료 할당이
    0이라(실측) 쓸 수 없었다. 그래서 이미지는 OpenAI로 보낸다.
    한쪽 키만 있어도 그쪽만 동작하고, 나머지는 폴백으로 처리된다.
    """

    port: int
    host: str
    # 키는 서버에만 존재한다. 클라이언트(WebGL)로 절대 내려보내지 않는다.
    gemini_api_key: str | None
    openai_api_key: str | None
    # 그림 + 메모 → 스탯 JSON (Gemini)
    stats_model: str
    # 그림 → 무기 이미지 (OpenAI images/edits)
    image_model: str
    # 두 키가 모두 없어 목 구현으로 도는 중인가
    use_mock: bool
    # 호출 하나당 타임아웃(초). 이미지 생성이 느려 넉넉히 잡는다.
    timeout_s: float

    @property
    def has_stats_provider(self) -> bool:
        return not self.use_mock and self.gemini_api_key is not None

    @property
    def has_image_provider(self) -> bool:
        return not self.use_mock and self.openai_api_key is not None


def load_config(env: dict[str, str] | None = None) -> ServerConfig:
    src = os.environ if env is None else env
    gemini_key = (src.get("GEMINI_API_KEY") or "").strip() or None
    openai_key = (src.get("OPENAI_API_KEY") or "").strip() or None
    force_mock = (src.get("FORGE_MODE") or "").strip().lower() == "mock"

    return ServerConfig(
        port=int(src.get("PORT", "8790")),
        host=src.get("HOST", "127.0.0.1"),
        gemini_api_key=gemini_key,
        openai_api_key=openai_key,
        stats_model=src.get("GEMINI_STATS_MODEL", "gemini-flash-latest"),
        image_model=src.get("OPENAI_IMAGE_MODEL", "gpt-image-1.5"),
        use_mock=force_mock or (gemini_key is None and openai_key is None),
        timeout_s=float(src.get("FORGE_TIMEOUT_S", "180")),
    )
