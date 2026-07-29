"""서버 설정 — 환경변수 로드.

GEMINI_API_KEY가 없으면 목 모드로 뜬다. 목 모드에서도 /forge 응답 형태는 같아서
Unity 쪽 3버전 선택 흐름을 키 없이 끝까지 검증할 수 있다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    port: int
    host: str
    # 서버에만 존재한다. 클라이언트(WebGL)로 절대 내려보내지 않는다.
    gemini_api_key: str | None
    # 그림 + 메모 → 스탯 JSON
    stats_model: str
    # 그림 → 무기 이미지. 이미지 출력이 되는 모델이어야 한다.
    image_model: str
    # 키가 없어 목 구현으로 도는 중인가
    use_mock: bool
    # Gemini 호출 하나당 타임아웃(초)
    timeout_s: float


def load_config(env: dict[str, str] | None = None) -> ServerConfig:
    src = os.environ if env is None else env
    api_key = (src.get("GEMINI_API_KEY") or "").strip() or None
    force_mock = (src.get("FORGE_MODE") or "").strip().lower() == "mock"

    return ServerConfig(
        port=int(src.get("PORT", "8790")),
        host=src.get("HOST", "127.0.0.1"),
        gemini_api_key=api_key,
        stats_model=src.get("GEMINI_STATS_MODEL", "gemini-flash-latest"),
        image_model=src.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
        use_mock=force_mock or api_key is None,
        timeout_s=float(src.get("FORGE_TIMEOUT_S", "60")),
    )
