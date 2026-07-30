"""Cloudflare Workers AI 이미지 편집 어댑터 (httpx, async).

Stable Diffusion 1.5 img2img를 쓴다. 이 모델을 고른 이유가 있다 —
`strength`(0~1) 파라미터가 "원본을 얼마나 바꿀지"를 숫자로 정한다. Gemini·OpenAI에서는
"형태를 바꾸지 마라"를 프롬프트로 부탁해야 했지만, 여기서는 강제할 수 있다.

무료 계정에 하루 10,000 뉴런이 주어지고 카드 등록이 필요 없다.

주의: SD 1.5는 영어 프롬프트만 알아듣는다. 한글을 보내면 무시된다.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"


@dataclass(frozen=True)
class CloudflareImageOptions:
    account_id: str
    api_token: str
    model: str
    timeout_s: float
    # 프롬프트를 얼마나 따를지. SD 기본값이 7.5다.
    guidance: float = 7.5
    num_steps: int = 20


def _extract(response: httpx.Response) -> str:
    """이미지 base64를 꺼낸다.

    이미지 모델은 보통 원본 바이트를 그대로 돌려주지만, 계정·모델에 따라
    JSON(result.image에 base64)으로 오는 경우도 있어 둘 다 받는다.
    """
    content_type = response.headers.get("content-type", "")

    if content_type.startswith("image/"):
        return base64.b64encode(response.content).decode("ascii")

    payload: Any = response.json()
    if not payload.get("success", True):
        errors = payload.get("errors") or []
        raise RuntimeError(f"Workers AI 오류: {errors}")

    result = payload.get("result") or {}
    image = result.get("image")
    if not image:
        raise RuntimeError("응답에 이미지가 없음")
    return image


async def generate_image_edit(
    opts: CloudflareImageOptions,
    *,
    image_png: bytes,
    prompt: str,
    negative_prompt: str,
    strength: float,
) -> str:
    """그린 그림 + 영어 프롬프트 + strength → 편집된 이미지 base64."""
    url = ENDPOINT.format(account_id=opts.account_id, model=opts.model)
    body = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "image_b64": base64.b64encode(image_png).decode("ascii"),
        "strength": round(max(0.05, min(1.0, strength)), 3),
        "guidance": opts.guidance,
        "num_steps": opts.num_steps,
    }

    async with httpx.AsyncClient(timeout=opts.timeout_s) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {opts.api_token}",
                "content-type": "application/json",
            },
            json=body,
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"Workers AI 호출 실패 ({response.status_code}): {response.text[:300]}"
        )

    return _extract(response)
