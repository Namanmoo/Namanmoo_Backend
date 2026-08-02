"""무기고 — 저장·목록·이미지·삭제.

계정 개념이 없어 무기고는 하나뿐이고, 저장소는 파일시스템이다.
"""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.vault.store import WeaponNotFound, WeaponStore

from .conftest import make_config


def sample_png(color=(200, 30, 30), size=32) -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for x in range(4, size - 4):
        image.putpixel((x, size // 2), (*color, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def save(client: TestClient, name="불꽃 검", stage=1, damage=8.0, png=None):
    return client.post(
        "/weapons",
        files={"image": ("w.png", png or sample_png(), "image/png")},
        data={
            "name": name,
            "flavor": "설명",
            "stage": str(stage),
            "damage": str(damage),
            "shotsPerSecond": "3",
            "projectileSpeed": "8",
            "lifetime": "4",
        },
    )


@pytest.fixture
def config():
    return make_config()


@pytest.fixture
def client(config) -> TestClient:
    return TestClient(create_app(config))


def test_empty_vault_lists_nothing(client: TestClient):
    res = client.get("/weapons")

    assert res.status_code == 200
    assert res.json()["weapons"] == []


def test_saved_weapon_appears_in_the_list(client: TestClient):
    saved = save(client).json()

    assert saved["name"] == "불꽃 검"
    assert saved["stage"] == 1
    assert saved["id"]
    assert saved["createdAt"].endswith("+00:00")

    listed = client.get("/weapons").json()["weapons"]
    assert [w["id"] for w in listed] == [saved["id"]]


def test_newest_weapon_comes_first(client: TestClient):
    first = save(client, name="첫 번째").json()
    second = save(client, name="두 번째").json()

    listed = client.get("/weapons").json()["weapons"]

    assert [w["id"] for w in listed] == [second["id"], first["id"]]


def test_image_round_trips(client: TestClient):
    png = sample_png(color=(20, 60, 200), size=48)
    saved = save(client, png=png).json()

    res = client.get(f"/weapons/{saved['id']}/image")

    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(res.content)).size == (48, 48)


def test_delete_removes_metadata_and_image(client: TestClient):
    saved = save(client).json()

    assert client.delete(f"/weapons/{saved['id']}").status_code == 200
    assert client.get("/weapons").json()["weapons"] == []
    assert client.get(f"/weapons/{saved['id']}/image").status_code == 404


def test_deleting_twice_is_a_404(client: TestClient):
    saved = save(client).json()
    client.delete(f"/weapons/{saved['id']}")

    assert client.delete(f"/weapons/{saved['id']}").status_code == 404


def test_missing_image_is_a_404(client: TestClient):
    assert client.get("/weapons/nope/image").status_code == 404


def test_non_png_upload_is_rejected(client: TestClient):
    res = client.post(
        "/weapons",
        files={"image": ("w.png", b"not an image", "image/png")},
        data={
            "name": "검",
            "stage": "0",
            "damage": "5",
            "shotsPerSecond": "3",
            "projectileSpeed": "8",
            "lifetime": "4",
        },
    )

    assert res.status_code == 400


def test_out_of_range_stats_are_clamped_on_save(client: TestClient):
    # 클라이언트가 보낸 값을 그대로 믿으면 무기고를 통해 밸런스가 새어 나간다
    saved = save(client, damage=9999.0).json()

    assert saved["stats"]["damage"] <= 30


def test_blank_name_gets_a_placeholder(client: TestClient):
    saved = save(client, name="   ").json()

    assert saved["name"] == "이름 없는 무기"


def test_id_cannot_escape_the_store_directory(config):
    store = WeaponStore(config.data_dir / "weapons")

    path = store.image_path("../../etc/passwd")

    assert path.parent == config.data_dir / "weapons"
    assert path.name == "passwd.png"


def test_corrupt_index_yields_an_empty_vault(config):
    """목록이 깨졌다고 게임이 멈추면 안 된다."""
    store = WeaponStore(config.data_dir / "weapons")
    (config.data_dir / "weapons" / "index.json").write_text("{ broken", encoding="utf-8")

    assert store.list() == []


def test_index_survives_entries_it_cannot_parse(config):
    store = WeaponStore(config.data_dir / "weapons")
    good = {
        "id": "abc",
        "name": "검",
        "flavor": "",
        "stage": 0,
        "stats": {
            "damage": 5,
            "shotsPerSecond": 3,
            "projectileSpeed": 8,
            "lifetime": 4,
        },
        "createdAt": "2026-07-30T00:00:00+00:00",
    }
    (config.data_dir / "weapons" / "index.json").write_text(
        json.dumps([{"id": "bad"}, good]), encoding="utf-8"
    )

    weapons = store.list()

    assert [w.id for w in weapons] == ["abc"]


def test_store_get_raises_for_unknown_id(config):
    store = WeaponStore(config.data_dir / "weapons")

    with pytest.raises(WeaponNotFound):
        store.get("nope")
