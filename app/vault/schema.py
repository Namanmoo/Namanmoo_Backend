"""무기고에 저장되는 무기의 형태."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..forge.schema import MAX_STAGE, ForgeStats


class SavedWeapon(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=24)
    flavor: str = Field(default="", max_length=120)
    # 어떤 AI 개입 단계로 만들었는지 (0/1/2)
    stage: int = Field(ge=0, le=MAX_STAGE)
    stats: ForgeStats
    # ISO8601 UTC
    createdAt: str


class SavedWeaponList(BaseModel):
    weapons: list[SavedWeapon]
