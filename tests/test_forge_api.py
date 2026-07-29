"""/forge 엔드포인트 — 목 모드 응답과 실패 폴백 동작."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import ServerConfig
from app.forge.service import run_forge
from app.main import create_app


def mock_config(**overrides) -> ServerConfig:
    base = dict(
        port=8790,
        host="127.0.0.1",
        gemini_api_key=None,
        stats_model="stub",
        image_model="stub",
        use_mock=True,
        timeout_s=5,
    )
    base.update(overrides)
    return ServerConfig(**base)


def sample_png(color=(200, 30, 30)) -> bytes:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(10, 54):
        for y in range(28, 36):
            image.putpixel((x, y), (*color, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(mock_config()))


def test_healthz_reports_mock(client: TestClient):
    res = client.get("/healthz")

    assert res.status_code == 200
    assert res.json()["source"] == "mock"


def test_forge_returns_three_variants(client: TestClient):
    res = client.post(
        "/forge",
        files={"drawing": ("drawing.png", sample_png(), "image/png")},
        data={"note": "불이 나오는 검"},
    )

    assert res.status_code == 200
    body = res.json()
    assert [v["version"] for v in body["variants"]] == [1, 2, 3]
    # 1번은 클라이언트가 원본을 쓰므로 이미지가 비어 있어야 한다
    assert body["variants"][0]["image"] == ""
    assert body["variants"][1]["image"] != ""
    assert body["variants"][2]["image"] != ""
    assert body["fallback"] is False
    assert body["source"] == "mock"


def test_generated_variants_are_valid_pngs_and_differ(client: TestClient):
    res = client.post(
        "/forge",
        files={"drawing": ("drawing.png", sample_png(), "image/png")},
        data={"note": ""},
    )
    variants = res.json()["variants"]

    images = [base64.b64decode(v["image"]) for v in variants[1:]]
    for raw in images:
        assert Image.open(io.BytesIO(raw)).size == (64, 64)
    # 두 버전이 같은 그림이면 선택 UI가 의미 없다
    assert images[0] != images[1]


def test_same_drawing_and_note_give_same_stats(client: TestClient):
    png = sample_png()
    first = client.post(
        "/forge", files={"drawing": ("d.png", png, "image/png")}, data={"note": "얼음"}
    ).json()
    second = client.post(
        "/forge", files={"drawing": ("d.png", png, "image/png")}, data={"note": "얼음"}
    ).json()

    assert first["stats"] == second["stats"]
    assert first["name"] == second["name"]


def test_rejects_non_png(client: TestClient):
    res = client.post(
        "/forge",
        files={"drawing": ("drawing.txt", b"not an image", "image/png")},
        data={"note": ""},
    )

    assert res.status_code == 400


def test_rejects_empty_upload(client: TestClient):
    res = client.post(
        "/forge",
        files={"drawing": ("drawing.png", b"", "image/png")},
        data={"note": ""},
    )

    assert res.status_code == 400


@pytest.mark.asyncio
async def test_stats_failure_falls_back_but_still_returns_images():
    """스탯이 끝내 실패해도 기본 무기로 게임은 진행되어야 한다."""

    class BrokenStatsEngine:
        name = "broken"

        async def stats(self, png: bytes, note: str):
            raise RuntimeError("모델이 응답하지 않음")

        async def image(self, png: bytes, note: str, version: int) -> str:
            return "ZmFrZQ=="

    result = await run_forge(BrokenStatsEngine(), drawing=sample_png(), note="")

    assert result.fallback is True
    assert result.name == "연필 막대"
    assert all(not v.failed for v in result.variants)


@pytest.mark.asyncio
async def test_image_failure_marks_variant_without_killing_request():
    class BrokenImageEngine:
        name = "broken-image"

        async def stats(self, png: bytes, note: str):
            return {
                "name": "테스트 검",
                "flavor": "설명",
                "stats": {
                    "damage": 5,
                    "shotsPerSecond": 3,
                    "projectileSpeed": 8,
                    "lifetime": 4,
                },
            }

        async def image(self, png: bytes, note: str, version: int) -> str:
            raise RuntimeError("이미지 모델 오류")

    result = await run_forge(BrokenImageEngine(), drawing=sample_png(), note="")

    assert result.fallback is False
    assert result.variants[0].failed is False
    assert result.variants[1].failed is True
    assert result.variants[2].failed is True
