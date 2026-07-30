"""Gemini generateContent 호출 어댑터 (httpx, async).

AIGame server/src/forge/llm.ts의 GeminiForgeLLM과 같은 엔드포인트·inline_data 형식을 쓴다.

주의: 이미지 출력 모델의 정확한 모델 ID와 responseModalities 동작은 실제 키를 넣고
한 번 확인해야 한다. 실패해도 파이프라인이 죽지 않도록 호출부(service.py)에서 흡수한다.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass(frozen=True)
class GeminiCallOptions:
    api_key: str
    model: str
    timeout_s: float


async def _call(opts: GeminiCallOptions, body: dict[str, Any]) -> dict[str, Any]:
    url = f"{ENDPOINT}/{opts.model}:generateContent"
    async with httpx.AsyncClient(timeout=opts.timeout_s) as client:
        res = await client.post(
            url,
            params={"key": opts.api_key},
            json=body,
            headers={"content-type": "application/json"},
        )
        if res.status_code != 200:
            # 300자로 자르다가 쿼터 이름("...PerDayPerProjectPerModel")이 잘려
            # 분당 한도인지 일일 한도인지 로그만 보고는 알 수 없었다.
            raise RuntimeError(
                f"Gemini 호출 실패 ({res.status_code}): {_summarise_error(res)}"
            )
        return res.json()


def _summarise_error(response: httpx.Response) -> str:
    """오류에서 진단에 필요한 것만 한 줄로 — 쿼터 이름과 재시도 권고를 남긴다."""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return response.text[:300]

    pieces = [error.get("status") or "", (error.get("message") or "").split("\n")[0][:160]]

    for detail in error.get("details") or []:
        kind = detail.get("@type", "")
        if "QuotaFailure" in kind:
            for violation in detail.get("violations") or []:
                pieces.append(f"quota={violation.get('quotaId')}")
        elif "RetryInfo" in kind:
            pieces.append(f"retryAfter={detail.get('retryDelay')}")

    # limit: N 은 message 안에 있어 따로 뽑는다
    for part in (error.get("message") or "").split("*"):
        if "limit:" in part:
            pieces.append(part.strip()[:80])

    return " | ".join(p for p in pieces if p)


def _parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates") or []
    if not candidates:
        return []
    return (candidates[0].get("content") or {}).get("parts") or []


def _text_of(payload: dict[str, Any]) -> str:
    return "\n".join(p["text"] for p in _parts(payload) if p.get("text"))


def _image_of(payload: dict[str, Any]) -> str | None:
    """첫 번째 이미지의 base64. 카멜/스네이크 표기 둘 다 받는다."""
    for part in _parts(payload):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return inline["data"]
    return None


def parse_json_loose(text: str) -> Any:
    """```json 블록이나 앞뒤 군말이 섞여도 JSON 객체를 건져낸다."""
    trimmed = re.sub(r"^```(?:json)?", "", text.strip())
    trimmed = re.sub(r"```$", "", trimmed).strip()
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        start = trimmed.find("{")
        end = trimmed.rfind("}")
        if start >= 0 and end > start:
            return json.loads(trimmed[start : end + 1])
        raise ValueError(f"JSON을 찾을 수 없음: {text[:200]}") from None


def _blocked_reason(payload: dict[str, Any]) -> str | None:
    feedback = payload.get("promptFeedback") or {}
    return feedback.get("blockReason")


async def generate_json(
    opts: GeminiCallOptions,
    *,
    image_png: bytes,
    system: str,
    prompt: str,
    response_schema: dict[str, Any] | None = None,
) -> Any:
    """그림 + 프롬프트 → JSON 응답.

    스키마를 주면 구조화 출력을 켠다. 이게 핵심이다 — 스키마 없이는 모델이
    "제시해주신 무기의 디자인에 맞추어… ### 🗡️" 같은 마크다운 산문을 내보내
    파싱이 깨졌다.

    maxOutputTokens는 1024에서 올렸다. 그 값에서는 응답이 문장 중간에서 잘렸다.

    thinkingConfig는 넣지 않는다. gemini-flash-latest에 thinkingBudget 0을 주면
    400 INVALID_ARGUMENT로 거부한다(실측). 스키마만으로 충분하다.
    """
    generation_config: dict[str, Any] = {
        "maxOutputTokens": 4096,
        "temperature": 1.0,
    }
    if response_schema is not None:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = response_schema

    payload = await _call(
        opts,
        {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(image_png).decode("ascii"),
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": generation_config,
        },
    )

    text = _text_of(payload)
    if not text:
        blocked = _blocked_reason(payload)
        raise RuntimeError(f"응답이 차단됨: {blocked}" if blocked else "빈 응답")
    return parse_json_loose(text)


async def generate_image(
    opts: GeminiCallOptions, *, image_png: bytes, prompt: str
) -> str:
    """그림 + 프롬프트 → 이미지 base64."""
    payload = await _call(
        opts,
        {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(image_png).decode("ascii"),
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        },
    )

    image = _image_of(payload)
    if not image:
        blocked = _blocked_reason(payload)
        raise RuntimeError(
            f"이미지 생성이 차단됨: {blocked}" if blocked else "응답에 이미지가 없음"
        )
    return image
