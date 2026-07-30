"""테스트 공용 설정 만들기.

ServerConfig에 필드가 늘 때마다 테스트마다 고치지 않도록 한 곳에 모아 둔다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.config import ServerConfig


def make_config(**overrides) -> ServerConfig:
    base = dict(
        port=8790,
        host="127.0.0.1",
        gemini_api_key=None,
        openai_api_key=None,
        cloudflare_account_id=None,
        cloudflare_api_token=None,
        stats_model="stub-stats",
        openai_image_model="stub-openai",
        cloudflare_image_model="stub-cf",
        image_provider_override=None,
        use_mock=True,
        timeout_s=5,
        data_dir=Path(tempfile.mkdtemp(prefix="namanmoo-test-")),
    )
    base.update(overrides)
    return ServerConfig(**base)
