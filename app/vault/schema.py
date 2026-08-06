"""무기고에 저장되는 무기의 형태."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..forge.schema import MAX_STAGE, ForgeWeapon


class SavedWeapon(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=24)
    flavor: str = Field(default="", max_length=200)
    # 어떤 AI 개입 단계로 만들었는지 (0/1/2)
    stage: int = Field(ge=0, le=MAX_STAGE)
    # 스탯뿐 아니라 분류·궤도·효과까지 통째로 — 무기고에서 꺼내도 같은 무기여야 한다
    weapon: ForgeWeapon
    # 그리기 화면에서 찍은 기준점들 (0~1, 왼쪽 아래 원점).
    # 그립은 잡는 자리(스프라이트 pivot), 끝은 칼끝 — 그립→끝이 무기의 축이다.
    # 중심은 무기 몸통의 가운데. 기준점 없이 저장된 옛 무기는 기본값을 쓴다.
    gripX: float = Field(default=0.5, ge=0.0, le=1.0)
    gripY: float = Field(default=0.5, ge=0.0, le=1.0)
    centerX: float = Field(default=0.5, ge=0.0, le=1.0)
    centerY: float = Field(default=0.75, ge=0.0, le=1.0)
    tipX: float = Field(default=0.5, ge=0.0, le=1.0)
    tipY: float = Field(default=1.0, ge=0.0, le=1.0)
    # ISO8601 UTC
    createdAt: str


class SavedWeaponList(BaseModel):
    weapons: list[SavedWeapon]
