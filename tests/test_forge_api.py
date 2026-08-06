"""/forge 엔드포인트 — 단계별 응답과 실패 폴백 동작."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.forge.service import run_forge
from app.main import create_app

from .conftest import make_config




def sample_png(color=(200, 30, 30)) -> bytes:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(10, 54):
        for y in range(28, 36):
            image.putpixel((x, y), (*color, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def post(client: TestClient, stage: int, note: str = "", png: bytes | None = None):
    return client.post(
        "/forge",
        files={"drawing": ("drawing.png", png or sample_png(), "image/png")},
        data={"note": note, "stage": str(stage)},
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(make_config()))


def test_healthz_reports_mock(client: TestClient):
    res = client.get("/healthz")

    assert res.status_code == 200
    assert res.json()["source"] == "mock"


def test_stage_zero_does_not_generate_an_image(client: TestClient):
    """0단계는 개입이 없다 — 이미지 생성 호출도, 이미지도 없어야 한다."""
    body = post(client, stage=0).json()

    assert body["stage"] == 0
    assert body["image"] == ""
    assert body["imageFailed"] is False
    # 스탯은 0단계에서도 나온다
    damage = next(p["value"] for p in body["weapon"]["stats"] if p["key"] == "damage")
    assert damage > 0


@pytest.mark.parametrize("stage", [1, 2])
def test_generating_stages_return_an_image(client: TestClient, stage: int):
    body = post(client, stage=stage).json()

    assert body["stage"] == stage
    assert body["image"] != ""
    assert body["imageFailed"] is False
    assert Image.open(io.BytesIO(base64.b64decode(body["image"]))).size == (64, 64)


def test_stage_one_and_two_differ(client: TestClient):
    """단계가 결과를 바꾸지 않으면 슬라이더가 의미 없다."""
    png = sample_png()
    one = post(client, stage=1, png=png).json()["image"]
    two = post(client, stage=2, png=png).json()["image"]

    assert one != two


def test_stage_out_of_range_is_rejected(client: TestClient):
    assert post(client, stage=3).status_code == 400
    assert post(client, stage=-1).status_code == 400


def test_same_input_gives_same_stats(client: TestClient):
    png = sample_png()
    first = post(client, stage=1, note="얼음", png=png).json()
    second = post(client, stage=1, note="얼음", png=png).json()

    assert first["weapon"] == second["weapon"]
    assert first["name"] == second["name"]


def test_rejects_non_png(client: TestClient):
    res = client.post(
        "/forge",
        files={"drawing": ("drawing.txt", b"not an image", "image/png")},
        data={"note": "", "stage": "0"},
    )

    assert res.status_code == 400


def test_rejects_empty_upload(client: TestClient):
    res = client.post(
        "/forge",
        files={"drawing": ("drawing.png", b"", "image/png")},
        data={"note": "", "stage": "0"},
    )

    assert res.status_code == 400


@pytest.mark.asyncio
async def test_stats_failure_falls_back_but_still_returns_the_image():
    """스탯이 끝내 실패해도 기본 무기로 게임은 진행되어야 한다."""

    class BrokenStatsEngine:
        name = "broken"

        async def stats(self, png: bytes, note: str):
            raise RuntimeError("모델이 응답하지 않음")

        async def image(self, png: bytes, note: str, stage: int) -> str:
            return "ZmFrZQ=="

    result = await run_forge(BrokenStatsEngine(), drawing=sample_png(), note="", stage=2)

    assert result.fallback is True
    assert result.name == "연필 막대"
    assert result.image == "ZmFrZQ=="
    assert result.imageFailed is False


@pytest.mark.asyncio
async def test_image_failure_is_flagged_without_killing_the_request():
    class BrokenImageEngine:
        name = "broken-image"

        async def stats(self, png: bytes, note: str):
            return {
                "name": "테스트 검",
                "flavor": "설명",
                "category": "ranged",
                "weaponType": "Projectile",
                "stats": [
                    {"key": "damage", "value": 5},
                    {"key": "shotsPerSecond", "value": 3},
                    {"key": "projectileSpeed", "value": 8},
                    {"key": "lifetime", "value": 4},
                ],
                "delivery": {"deliveryId": "straight", "params": []},
                "effects": [],
                "effortScore": 0.3,
            }

        async def image(self, png: bytes, note: str, stage: int) -> str:
            raise RuntimeError("이미지 모델 오류")

    result = await run_forge(BrokenImageEngine(), drawing=sample_png(), note="", stage=1)

    assert result.fallback is False
    assert result.image == ""
    assert result.imageFailed is True


@pytest.mark.asyncio
async def test_stage_zero_never_calls_the_image_engine():
    """0단계에서 이미지 호출이 나가면 쓸데없이 API 비용이 든다."""
    calls: list[int] = []

    class CountingEngine:
        name = "counting"

        async def stats(self, png: bytes, note: str):
            return {
                "name": "검",
                "flavor": "설명",
                "category": "ranged",
                "weaponType": "Projectile",
                "stats": [
                    {"key": "damage", "value": 5},
                    {"key": "shotsPerSecond", "value": 3},
                    {"key": "projectileSpeed", "value": 8},
                    {"key": "lifetime", "value": 4},
                ],
                "delivery": {"deliveryId": "straight", "params": []},
                "effects": [],
                "effortScore": 0.3,
            }

        async def image(self, png: bytes, note: str, stage: int) -> str:
            calls.append(stage)
            return "ZmFrZQ=="

    await run_forge(CountingEngine(), drawing=sample_png(), note="", stage=0)
    assert calls == []

    await run_forge(CountingEngine(), drawing=sample_png(), note="", stage=2)
    assert calls == [2]
