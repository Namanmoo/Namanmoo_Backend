"""무기고 저장소 — 파일시스템.

프로토 단계라 SQLite 대신 파일로 둔다. 내용을 눈으로 열어볼 수 있고, 이미지가
그대로 파일이라 디버깅이 쉽다. 계정 개념이 없어 무기고는 하나뿐이다.

    data/weapons/index.json     메타데이터 목록 (최신순)
    data/weapons/<id>.png       무기 그림

index.json은 임시 파일에 쓴 뒤 교체한다 — 쓰다가 죽어도 목록이 깨지지 않는다.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .schema import SavedWeapon

INDEX_NAME = "index.json"


class WeaponNotFound(LookupError):
    """없는 무기를 지우거나 읽으려 할 때."""


class WeaponStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    # ── 경로 ──────────────────────────────────────────────

    @property
    def _index_path(self) -> Path:
        return self._root / INDEX_NAME

    def image_path(self, weapon_id: str) -> Path:
        # 바깥에서 온 id가 경로를 타고 올라가지 못하게 이름만 취한다
        safe = Path(weapon_id).name
        return self._root / f"{safe}.png"

    # ── 읽기 ──────────────────────────────────────────────

    def list(self) -> list[SavedWeapon]:
        if not self._index_path.exists():
            return []

        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 목록이 깨졌다고 게임이 멈추면 안 된다 — 빈 무기고로 시작한다
            return []

        weapons = []
        for item in raw if isinstance(raw, list) else []:
            try:
                weapons.append(SavedWeapon.model_validate(item))
            except Exception:
                continue  # 형태가 안 맞는 항목은 건너뛴다
        return weapons

    def get(self, weapon_id: str) -> SavedWeapon:
        for weapon in self.list():
            if weapon.id == weapon_id:
                return weapon
        raise WeaponNotFound(weapon_id)

    def read_image(self, weapon_id: str) -> bytes:
        path = self.image_path(weapon_id)
        if not path.exists():
            raise WeaponNotFound(weapon_id)
        return path.read_bytes()

    # ── 쓰기 ──────────────────────────────────────────────

    def save(self, weapon: SavedWeapon, image_png: bytes) -> SavedWeapon:
        self.image_path(weapon.id).write_bytes(image_png)
        # 최신이 앞으로 — 무기고 화면이 정렬을 신경 쓰지 않아도 되게
        self._write_index([weapon, *self.list()])
        return weapon

    def update(self, weapon: SavedWeapon) -> SavedWeapon:
        """같은 id의 항목을 통째로 바꾼다. 없으면 WeaponNotFound."""
        weapons = self.list()
        for index, existing in enumerate(weapons):
            if existing.id == weapon.id:
                weapons[index] = weapon
                self._write_index(weapons)
                return weapon
        raise WeaponNotFound(weapon.id)

    def delete(self, weapon_id: str) -> None:
        remaining = [w for w in self.list() if w.id != weapon_id]
        if len(remaining) == len(self.list()):
            raise WeaponNotFound(weapon_id)

        self._write_index(remaining)
        self.image_path(weapon_id).unlink(missing_ok=True)

    def _write_index(self, weapons: list[SavedWeapon]) -> None:
        payload = [weapon.model_dump() for weapon in weapons]
        temp = self._index_path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 원자적 교체 — 쓰다가 죽어도 이전 목록이 남는다
        os.replace(temp, self._index_path)


def new_weapon_id() -> str:
    return uuid.uuid4().hex


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
