"""서버 설정 — 환경변수 로드.

GEMINI_API_KEY가 없으면 목 모드로 뜬다. 목 모드에서도 /forge 응답 형태는 같아서
Unity 쪽 3버전 선택 흐름을 키 없이 끝까지 검증할 수 있다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    cloudflare_account_id: str | None
    cloudflare_api_token: str | None
    # 그림 + 메모 → 스탯 JSON (Gemini)
    stats_model: str
    # 그림 → 무기 이미지 (제공자에 따라 모델 이름이 다르다)
    openai_image_model: str
    cloudflare_image_model: str
    # 어떤 이미지 제공자를 쓸지 강제 (없으면 있는 자격증명으로 자동 선택)
    image_provider_override: str | None
    # 아무 자격증명도 없어 목 구현으로 도는 중인가
    use_mock: bool
    # 호출 하나당 타임아웃(초). 이미지 생성이 느려 넉넉히 잡는다.
    timeout_s: float
    # 무기고 저장 위치
    data_dir: Path

    @property
    def has_stats_provider(self) -> bool:
        return not self.use_mock and self.gemini_api_key is not None

    @property
    def image_provider(self) -> str | None:
        """'cloudflare' | 'openai' | None.

        Cloudflare를 먼저 본다 — 무료 할당이 있고 img2img strength로 단계를
        숫자로 제어할 수 있어서다. OpenAI는 크레딧이 있을 때의 대안이다.
        """
        if self.use_mock:
            return None

        has_cloudflare = bool(self.cloudflare_account_id and self.cloudflare_api_token)
        has_openai = bool(self.openai_api_key)

        if self.image_provider_override == "cloudflare":
            return "cloudflare" if has_cloudflare else None
        if self.image_provider_override == "openai":
            return "openai" if has_openai else None

        if has_cloudflare:
            return "cloudflare"
        if has_openai:
            return "openai"
        return None

    @property
    def image_model(self) -> str | None:
        provider = self.image_provider
        if provider == "cloudflare":
            return self.cloudflare_image_model
        if provider == "openai":
            return self.openai_image_model
        return None


def load_config(env: dict[str, str] | None = None) -> ServerConfig:
    src = os.environ if env is None else env

    def value(name: str) -> str | None:
        return (src.get(name) or "").strip() or None

    gemini_key = value("GEMINI_API_KEY")
    openai_key = value("OPENAI_API_KEY")
    cf_account = value("CLOUDFLARE_ACCOUNT_ID")
    cf_token = value("CLOUDFLARE_API_TOKEN")
    force_mock = (src.get("FORGE_MODE") or "").strip().lower() == "mock"

    override = (src.get("IMAGE_PROVIDER") or "").strip().lower() or None
    if override not in (None, "cloudflare", "openai"):
        raise ValueError(
            f"IMAGE_PROVIDER는 cloudflare 또는 openai여야 합니다: {override}"
        )

    nothing_configured = not any((gemini_key, openai_key, cf_account and cf_token))

    return ServerConfig(
        port=int(src.get("PORT", "8790")),
        host=src.get("HOST", "127.0.0.1"),
        gemini_api_key=gemini_key,
        openai_api_key=openai_key,
        cloudflare_account_id=cf_account,
        cloudflare_api_token=cf_token,
        stats_model=src.get("GEMINI_STATS_MODEL", "gemini-flash-lite-latest"),
        openai_image_model=src.get("OPENAI_IMAGE_MODEL", "gpt-image-1.5"),
        cloudflare_image_model=src.get(
            "CLOUDFLARE_IMAGE_MODEL", "@cf/runwayml/stable-diffusion-v1-5-img2img"
        ),
        image_provider_override=override,
        use_mock=force_mock or nothing_configured,
        timeout_s=float(src.get("FORGE_TIMEOUT_S", "180")),
        data_dir=Path(src.get("DATA_DIR", "data")),
    )
