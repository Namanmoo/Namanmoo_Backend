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


def weapon_json(damage=8.0) -> str:
    return json.dumps(
        {
            "category": "ranged",
            "weaponType": "Projectile",
            "stats": [
                {"key": "damage", "value": damage},
                {"key": "shotsPerSecond", "value": 3},
                {"key": "projectileSpeed", "value": 8},
                {"key": "lifetime", "value": 4},
            ],
            "delivery": {"deliveryId": "straight", "params": []},
            "effects": [
                {
                    "effectId": "pierce",
                    "triggerId": "on_hit",
                    "params": [{"key": "maxPierceCount", "value": 2}],
                }
            ],
        }
    )


def save(client: TestClient, name="불꽃 검", stage=1, damage=8.0, png=None, grip=None):
    data = {
        "name": name,
        "flavor": "설명",
        "stage": str(stage),
        "weapon": weapon_json(damage),
    }
    if grip is not None:
        data["gripX"], data["gripY"] = str(grip[0]), str(grip[1])

    return client.post(
        "/weapons",
        files={"image": ("w.png", png or sample_png(), "image/png")},
        data=data,
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
            "weapon": weapon_json(),
        },
    )

    assert res.status_code == 400


def test_out_of_range_stats_are_clamped_on_save(client: TestClient):
    # 클라이언트가 보낸 값을 그대로 믿으면 무기고를 통해 밸런스가 새어 나간다
    saved = save(client, damage=9999.0).json()

    damage = next(p["value"] for p in saved["weapon"]["stats"] if p["key"] == "damage")
    assert damage <= 30


def test_grip_round_trips(client: TestClient):
    # 그리기 화면에서 찍은 그립이 무기고를 다녀와도 살아 있어야 한다
    saved = save(client, grip=(0.2, 0.9)).json()

    assert saved["gripX"] == pytest.approx(0.2)
    assert saved["gripY"] == pytest.approx(0.9)

    listed = client.get("/weapons").json()["weapons"][0]
    assert listed["gripX"] == pytest.approx(0.2)
    assert listed["gripY"] == pytest.approx(0.9)


def test_missing_grip_defaults_to_the_center(client: TestClient):
    # 그립을 안 보내는 옛 클라이언트도 저장은 되어야 한다
    saved = save(client).json()

    assert saved["gripX"] == pytest.approx(0.5)
    assert saved["gripY"] == pytest.approx(0.5)


def test_out_of_range_grip_is_clamped(client: TestClient):
    saved = save(client, grip=(-3.0, 7.0)).json()

    assert saved["gripX"] == pytest.approx(0.0)
    assert saved["gripY"] == pytest.approx(1.0)


def test_index_entries_without_grip_still_parse(config):
    """그립 필드가 없던 시절의 index.json도 그대로 읽혀야 한다."""
    store = WeaponStore(config.data_dir / "weapons")
    old = {
        "id": "old",
        "name": "옛 검",
        "flavor": "",
        "stage": 0,
        "weapon": json.loads(weapon_json(damage=5)),
        "createdAt": "2026-07-30T00:00:00+00:00",
    }
    (config.data_dir / "weapons" / "index.json").write_text(
        json.dumps([old]), encoding="utf-8"
    )

    weapons = store.list()

    assert weapons[0].gripX == pytest.approx(0.5)
    assert weapons[0].gripY == pytest.approx(0.5)


def test_center_and_tip_round_trip(client: TestClient):
    saved = save(client).json()  # 안 보내면 기본값 — 위로 뻗은 그림
    assert saved["centerX"] == pytest.approx(0.5)
    assert saved["centerY"] == pytest.approx(0.75)
    assert saved["tipX"] == pytest.approx(0.5)
    assert saved["tipY"] == pytest.approx(1.0)

    res = client.post(
        "/weapons",
        files={"image": ("w.png", sample_png(), "image/png")},
        data={
            "name": "대각 검",
            "stage": "0",
            "weapon": weapon_json(),
            "gripX": "0.1", "gripY": "0.2",
            "centerX": "0.4", "centerY": "0.5",
            "tipX": "0.9", "tipY": "0.8",
        },
    )
    saved = res.json()
    assert saved["centerX"] == pytest.approx(0.4)
    assert saved["tipX"] == pytest.approx(0.9)
    assert saved["tipY"] == pytest.approx(0.8)


def test_patch_points_updates_only_the_points(client: TestClient):
    # 무기고 수정 화면 — 그림·스탯은 그대로, 기준점만 바뀌어야 한다
    saved = save(client, name="수정 검").json()

    res = client.patch(
        f"/weapons/{saved['id']}/points",
        data={
            "gripX": "0.15", "gripY": "0.25",
            "centerX": "0.5", "centerY": "0.6",
            "tipX": "0.85", "tipY": "0.95",
        },
    )

    assert res.status_code == 200
    updated = res.json()
    assert updated["gripX"] == pytest.approx(0.15)
    assert updated["tipY"] == pytest.approx(0.95)
    assert updated["name"] == "수정 검"
    assert updated["weapon"] == saved["weapon"]

    listed = client.get("/weapons").json()["weapons"][0]
    assert listed["gripX"] == pytest.approx(0.15)
    assert listed["centerY"] == pytest.approx(0.6)


def test_patch_points_on_a_missing_weapon_is_a_404(client: TestClient):
    res = client.patch(
        "/weapons/nope/points",
        data={
            "gripX": "0.5", "gripY": "0.5",
            "centerX": "0.5", "centerY": "0.75",
            "tipX": "0.5", "tipY": "1.0",
        },
    )

    assert res.status_code == 404


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
        "weapon": json.loads(weapon_json(damage=5)),
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
