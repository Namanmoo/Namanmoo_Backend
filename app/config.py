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
    # Gemini 이미지 모델 — IMAGE_PROVIDER=gemini일 때만 쓴다.
    # 무료 티어는 이미지 할당이 0이라(실측) 결제 활성화(Tier 1)가 필요하다.
    gemini_image_model: str = "gemini-2.5-flash-image"
    # 하루 Gemini 이미지 생성 성공 횟수 상한 — 콘솔에는 이미지 모델의 일일
    # 할당량 항목이 없어서(실측) 서버가 직접 센다. 초과분은 다음 제공자로 폴백.
    # None이면 무제한 (선불 잔액이 최종 상한).
    gemini_image_daily_limit: int | None = None

    @property
    def has_stats_provider(self) -> bool:
        return not self.use_mock and self.gemini_api_key is not None

    @property
    def image_provider_chain(self) -> tuple[tuple[str, str | None], ...]:
        """시도 순서대로의 (제공자, 모델) 목록 — 자격증명 없는 항목은 걸러진다.

        IMAGE_PROVIDER에 쉼표로 순서를 지정하고, 항목마다 `제공자:모델`로 모델을
        고정할 수 있다. 모델을 생략하면 그 제공자의 기본 모델(*_IMAGE_MODEL)을 쓴다.

            IMAGE_PROVIDER=gemini:gemini-3.1-flash-image,gemini,cloudflare
            → 나노바나나2 → 나노바나나(기본) → SD1.5 순서로 폴백

        지정이 없으면 기존처럼 Cloudflare 우선 단일 제공자 — 무료 할당이 있고
        strength로 단계를 숫자로 제어할 수 있어서다. Gemini는 무료 이미지 할당이
        0이라(실측) 명시했을 때만 체인에 들어간다.
        """
        if self.use_mock:
            return ()

        has = {
            "gemini": bool(self.gemini_api_key),
            "openai": bool(self.openai_api_key),
            "cloudflare": bool(
                self.cloudflare_account_id and self.cloudflare_api_token
            ),
        }

        if self.image_provider_override:
            chain: list[tuple[str, str | None]] = []
            for part in self.image_provider_override.split(","):
                part = part.strip()
                if not part:
                    continue
                provider, _, model = part.partition(":")
                if has[provider]:
                    chain.append((provider, model.strip() or None))
            return tuple(chain)

        if has["cloudflare"]:
            return (("cloudflare", None),)
        if has["openai"]:
            return (("openai", None),)
        return ()

    @property
    def image_provider(self) -> str | None:
        """체인의 첫 제공자 — 기존 호출부와 표시용."""
        chain = self.image_provider_chain
        return chain[0][0] if chain else None

    def default_image_model(self, provider: str) -> str:
        """제공자의 기본 모델 — 체인 항목에 모델이 명시되지 않았을 때 쓴다."""
        if provider == "cloudflare":
            return self.cloudflare_image_model
        if provider == "openai":
            return self.openai_image_model
        return self.gemini_image_model

    @property
    def image_model(self) -> str | None:
        chain = self.image_provider_chain
        if not chain:
            return None
        provider, model = chain[0]
        return model or self.default_image_model(provider)


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
    if override is not None:
        for part in override.split(","):
            provider = part.strip().partition(":")[0]
            if provider not in ("cloudflare", "openai", "gemini"):
                raise ValueError(
                    "IMAGE_PROVIDER는 cloudflare, openai, gemini를 쉼표로 나열해야"
                    f" 합니다 (모델 고정은 '제공자:모델'): {override}"
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
        gemini_image_model=src.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
        gemini_image_daily_limit=(
            int(daily_limit)
            if (daily_limit := (src.get("GEMINI_IMAGE_DAILY_LIMIT") or "").strip())
            else None
        ),
    )
