"""NaManMoo 무기 생성 API.

POST /forge — multipart: drawing(PNG) + note(추가 설정) + stage(0/1/2)
             → 이름/설명/스탯 + 요청한 단계의 무기 이미지 한 장
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .config import ServerConfig, load_config
from .forge.clamp import clamp_stats
from .forge.schema import MAX_STAGE, ForgeResponse, ForgeStats
from .forge.service import create_engine, run_forge
from .vault.schema import SavedWeapon, SavedWeaponList
from .vault.store import WeaponNotFound, WeaponStore, new_weapon_id, utc_now_iso

logger = logging.getLogger("namanmoo.forge")

# 그림 업로드 상한 — Unity 캔버스가 512x512 PNG라 넉넉하다
MAX_DRAWING_BYTES = 8 * 1024 * 1024
MAX_NOTE_LENGTH = 200


def create_app(config: ServerConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    app = FastAPI(title="NaManMoo Forge API", version="0.1.0")

    # WebGL 빌드는 브라우저에서 다른 오리진으로 호출한다.
    # 프로토 단계라 전부 허용하고, 배포 시 도메인을 좁힌다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    engine = create_engine(cfg)
    app.state.config = cfg
    app.state.engine = engine

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {
            "ok": True,
            "source": engine.name,
            "stats": {
                "provider": "gemini" if cfg.has_stats_provider else None,
                "model": cfg.stats_model if cfg.has_stats_provider else None,
            },
            "image": {
                "provider": cfg.image_provider,
                "model": cfg.image_model,
            },
        }

    @app.post("/forge", response_model=ForgeResponse)
    async def forge(
        drawing: UploadFile = File(...),
        note: str = Form(""),
        stage: int = Form(0),
    ) -> ForgeResponse:
        png = await drawing.read()
        if not png:
            raise HTTPException(status_code=400, detail="그림이 비어 있습니다.")
        if len(png) > MAX_DRAWING_BYTES:
            raise HTTPException(status_code=413, detail="그림이 너무 큽니다.")
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=400, detail="PNG 파일이 아닙니다.")
        if stage < 0 or stage > MAX_STAGE:
            raise HTTPException(
                status_code=400, detail=f"stage는 0~{MAX_STAGE} 사이여야 합니다."
            )

        result = await run_forge(
            app.state.engine,
            drawing=png,
            note=note[:MAX_NOTE_LENGTH],
            stage=stage,
            log=logger.warning,
        )
        logger.info(
            "forge 완료 — source=%s stage=%s name=%s fallback=%s 이미지실패=%s",
            result.source,
            result.stage,
            result.name,
            result.fallback,
            result.imageFailed,
        )
        return result

    # ── 무기고 ──────────────────────────────────────────────

    store = WeaponStore(cfg.data_dir / "weapons")
    app.state.store = store

    @app.get("/weapons", response_model=SavedWeaponList)
    async def list_weapons() -> SavedWeaponList:
        return SavedWeaponList(weapons=store.list())

    @app.post("/weapons", response_model=SavedWeapon)
    async def save_weapon(
        image: UploadFile = File(...),
        name: str = Form(...),
        flavor: str = Form(""),
        stage: int = Form(0),
        damage: float = Form(...),
        shotsPerSecond: float = Form(...),
        projectileSpeed: float = Form(...),
        lifetime: float = Form(...),
    ) -> SavedWeapon:
        png = await image.read()
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=400, detail="PNG 파일이 아닙니다.")
        if len(png) > MAX_DRAWING_BYTES:
            raise HTTPException(status_code=413, detail="그림이 너무 큽니다.")

        # 무기고에 들어가는 값도 게임 범위로 조인다 — 클라이언트를 믿지 않는다
        stats, _ = clamp_stats(
            ForgeStats(
                damage=damage,
                shotsPerSecond=shotsPerSecond,
                projectileSpeed=projectileSpeed,
                lifetime=lifetime,
            )
        )

        try:
            weapon = SavedWeapon(
                id=new_weapon_id(),
                name=name.strip()[:24] or "이름 없는 무기",
                flavor=flavor.strip()[:120],
                stage=stage,
                stats=stats,
                createdAt=utc_now_iso(),
            )
        except ValidationError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

        saved = store.save(weapon, png)
        logger.info("무기 저장 — %s (%s단계) %s", saved.name, saved.stage, saved.id)
        return saved

    @app.get("/weapons/{weapon_id}/image")
    async def weapon_image(weapon_id: str) -> Response:
        try:
            png = store.read_image(weapon_id)
        except WeaponNotFound as err:
            raise HTTPException(status_code=404, detail="없는 무기입니다.") from err

        return Response(content=png, media_type="image/png")

    @app.delete("/weapons/{weapon_id}")
    async def delete_weapon(weapon_id: str) -> dict[str, bool]:
        try:
            store.delete(weapon_id)
        except WeaponNotFound as err:
            raise HTTPException(status_code=404, detail="없는 무기입니다.") from err

        logger.info("무기 삭제 — %s", weapon_id)
        return {"ok": True}

    return app


app = create_app()
