# NaManMoo 무기 생성 API — Cloud Run 배포용.
#
#   docker build -t namanmoo-forge .
#   docker run --rm -p 8080:8080 namanmoo-forge          # 키 없이 목 모드
#
# Cloud Run은 PORT 환경변수를 주입한다(기본 8080). 키(GEMINI_API_KEY 등)는
# 이미지에 굽지 않고 배포 시 환경변수로 넣는다.
FROM python:3.13-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 컨테이너 밖에서 요청을 받으려면 0.0.0.0 이어야 한다 (기본값은 127.0.0.1).
ENV HOST=0.0.0.0 PORT=8080 DATA_DIR=/srv/data

# 무기고 저장 위치. Cloud Run 파일시스템은 휘발성이라 인스턴스가 내려가면
# 사라진다 — 영구 보관하려면 이 경로에 GCS 볼륨을 마운트한다 (README 참고).
VOLUME /srv/data

CMD exec uvicorn app.main:app --host "$HOST" --port "$PORT"
