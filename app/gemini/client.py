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
            raise RuntimeError(
                f"Gemini 호출 실패 ({res.status_code}): {res.text[:300]}"
            )
        return res.json()


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
    opts: GeminiCallOptions, *, image_png: bytes, system: str, prompt: str
) -> Any:
    """그림 + 프롬프트 → JSON 응답."""
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
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 1.0},
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
