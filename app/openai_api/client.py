"""OpenAI 이미지 편집 어댑터 (httpx, async).

무기 그림 생성은 Gemini가 아니라 여기로 간다. Gemini 이미지 모델은 무료 티어
할당이 0이라(실측: limit 0) 쓸 수 없었고, OpenAI는 신규 계정 크레딧으로
시험할 수 있다.

`/v1/images/edits`를 쓴다 — 그린 그림을 입력으로 받아야 하므로 text-to-image가
아니라 image-to-image가 필요하다. mask는 없어도 된다.

모델마다 받는 파라미터가 다르다(gpt-image-2는 input_fidelity를 거부한다고
문서에 명시). 그래서 선택 파라미터를 붙여 한 번 시도하고, 400이면 최소 형태로
한 번 더 시도한다. 오늘 Gemini에서 thinkingConfig 하나 때문에 전체가 400으로
죽는 걸 겪었기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

ENDPOINT = "https://api.openai.com/v1/images/edits"


@dataclass(frozen=True)
class OpenAIImageOptions:
    api_key: str
    model: str
    timeout_s: float
    size: str = "1024x1024"
    # 투명 배경으로 받으면 클라이언트의 흰 배경 제거가 사실상 필요 없어진다
    background: str = "transparent"
    output_format: str = "png"


def _optional_fields(opts: OpenAIImageOptions) -> dict[str, str]:
    return {
        "size": opts.size,
        "background": opts.background,
        "output_format": opts.output_format,
    }


async def _post(
    opts: OpenAIImageOptions, prompt: str, image_png: bytes, extra: dict[str, str]
) -> httpx.Response:
    data = {"model": opts.model, "prompt": prompt}
    data.update(extra)

    async with httpx.AsyncClient(timeout=opts.timeout_s) as client:
        return await client.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {opts.api_key}"},
            data=data,
            files={"image": ("drawing.png", image_png, "image/png")},
        )


def _looks_like_parameter_problem(response: httpx.Response) -> bool:
    """400이 '파라미터가 안 맞아서'인지 판별한다.

    결제 한도(billing_hard_limit_reached)나 인증 문제도 400으로 오는데, 그건
    파라미터를 빼고 다시 보내도 똑같이 실패한다 — 실패한 호출을 두 번 하는 셈이라
    구분해서 한 번만 시도한다.
    """
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return False

    if error.get("param"):
        return True

    code = (error.get("code") or "").lower()
    if "billing" in code or "quota" in code or "limit" in code:
        return False

    message = (error.get("message") or "").lower()
    return any(
        hint in message
        for hint in ("unknown parameter", "unsupported", "invalid value", "not supported")
    )


def _extract(payload: dict[str, Any]) -> str:
    items = payload.get("data") or []
    if not items:
        raise RuntimeError("응답에 이미지가 없음")

    image = items[0].get("b64_json")
    if not image:
        raise RuntimeError("응답에 b64_json이 없음")
    return image


async def generate_image_edit(
    opts: OpenAIImageOptions, *, image_png: bytes, prompt: str
) -> str:
    """그림 + 프롬프트 → 편집된 이미지 base64.

    선택 파라미터가 모델에 안 맞으면(400) 최소 형태로 한 번 더 시도한다.
    """
    response = await _post(opts, prompt, image_png, _optional_fields(opts))

    if response.status_code == 400 and _looks_like_parameter_problem(response):
        # 모델이 선택 파라미터 중 하나를 거부한 경우 — 핵심만 남겨 다시 시도
        response = await _post(opts, prompt, image_png, {})

    if response.status_code != 200:
        body = response.text
        raise RuntimeError(f"OpenAI 호출 실패 ({response.status_code}): {body[:300]}")

    return _extract(response.json())
