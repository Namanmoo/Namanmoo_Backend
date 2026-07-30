"""OpenAI 이미지 호출 — 400을 어떻게 구분하는지.

실제로 겪은 두 가지 400이 있다:
- thinkingConfig처럼 모델이 파라미터를 거부하는 400 → 파라미터를 빼고 재시도할 값이 있다
- billing_hard_limit_reached → 몇 번 보내도 똑같이 실패한다. 재시도하면 낭비다
"""

from __future__ import annotations

import httpx
import pytest

from app.openai_api.client import (
    OpenAIImageOptions,
    _looks_like_parameter_problem,
    generate_image_edit,
)


def response(payload: dict, status: int = 400) -> httpx.Response:
    return httpx.Response(status_code=status, json=payload)


def test_billing_limit_is_not_treated_as_a_parameter_problem():
    res = response(
        {
            "error": {
                "message": "Billing hard limit has been reached.",
                "type": "billing_limit_user_error",
                "param": None,
                "code": "billing_hard_limit_reached",
            }
        }
    )

    assert _looks_like_parameter_problem(res) is False


def test_named_param_is_a_parameter_problem():
    res = response({"error": {"message": "Unknown parameter.", "param": "input_fidelity"}})

    assert _looks_like_parameter_problem(res) is True


def test_unsupported_message_is_a_parameter_problem():
    res = response({"error": {"message": "background is not supported for this model"}})

    assert _looks_like_parameter_problem(res) is True


def test_non_json_body_is_not_retried():
    res = httpx.Response(status_code=400, text="<html>gateway error</html>")

    assert _looks_like_parameter_problem(res) is False


@pytest.mark.asyncio
async def test_parameter_problem_retries_once_without_optional_fields(monkeypatch):
    calls: list[dict] = []

    async def fake_post(opts, prompt, image_png, extra):
        calls.append(extra)
        if extra:
            return response({"error": {"message": "Unknown parameter.", "param": "background"}})
        return httpx.Response(status_code=200, json={"data": [{"b64_json": "aGk="}]})

    monkeypatch.setattr("app.openai_api.client._post", fake_post)
    opts = OpenAIImageOptions(api_key="k", model="m", timeout_s=5)

    image = await generate_image_edit(opts, image_png=b"png", prompt="p")

    assert image == "aGk="
    assert len(calls) == 2
    assert calls[0] != {} and calls[1] == {}


@pytest.mark.asyncio
async def test_billing_error_is_not_retried(monkeypatch):
    calls: list[dict] = []

    async def fake_post(opts, prompt, image_png, extra):
        calls.append(extra)
        return response({"error": {"code": "billing_hard_limit_reached", "message": "no"}})

    monkeypatch.setattr("app.openai_api.client._post", fake_post)
    opts = OpenAIImageOptions(api_key="k", model="m", timeout_s=5)

    with pytest.raises(RuntimeError, match="400"):
        await generate_image_edit(opts, image_png=b"png", prompt="p")

    assert len(calls) == 1, "결제 문제로 실패한 호출을 두 번 보내면 낭비다"


@pytest.mark.asyncio
async def test_missing_image_in_response_raises(monkeypatch):
    async def fake_post(opts, prompt, image_png, extra):
        return httpx.Response(status_code=200, json={"data": []})

    monkeypatch.setattr("app.openai_api.client._post", fake_post)
    opts = OpenAIImageOptions(api_key="k", model="m", timeout_s=5)

    with pytest.raises(RuntimeError, match="이미지가 없음"):
        await generate_image_edit(opts, image_png=b"png", prompt="p")
