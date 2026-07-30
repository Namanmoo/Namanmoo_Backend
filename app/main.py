"""NaManMoo 무기 생성 API.

POST /forge — multipart: drawing(PNG) + note(추가 설정) + stage(0/1/2)
             → 이름/설명/스탯 + 요청한 단계의 무기 이미지 한 장
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import ServerConfig, load_config
from .forge.schema import MAX_STAGE, ForgeResponse
from .forge.service import create_engine, run_forge

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
            "statsModel": cfg.stats_model if not cfg.use_mock else None,
            "imageModel": cfg.image_model if not cfg.use_mock else None,
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

    return app


app = create_app()
