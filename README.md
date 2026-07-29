# NaManMoo Backend

무기 만들기(Weapon Forge) API. 플레이어가 그린 그림과 "추가 설정" 텍스트를 받아
**스탯**을 정하고 **무기 그림 3버전**을 돌려준다.

| 버전 | 내용 | 생성 |
| --- | --- | --- |
| 1 | 그린 그림 그대로 | 안 함 (클라이언트가 가진 원본 사용) |
| 2 | 형태는 유지하고 선·색만 다듬음 | Gemini 이미지 모델 |
| 3 | 컨셉만 살려 새로 그린 무기 아트 | Gemini 이미지 모델 |

## 실행

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

./run.sh            # http://127.0.0.1:8790
./run.sh --test     # pytest
```

`GEMINI_API_KEY`가 없으면 **목 모드**로 뜬다. 응답 형태가 동일해서 키 없이도
Unity 쪽 3버전 선택 흐름을 끝까지 검증할 수 있다. 목은 원본 그림을 실제로 가공해
버전마다 다른 이미지를 만든다 — "그림이 반영되는가"까지 확인된다.

키는 <https://aistudio.google.com/apikey> 에서 발급받아 `.env`에 넣는다
(`.env.example` 참고). 키는 서버에만 두고 클라이언트로 내려보내지 않는다.

## API

### `GET /healthz`
```json
{ "ok": true, "source": "mock", "statsModel": null, "imageModel": null }
```

### `POST /forge` (multipart)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `drawing` | file | PNG. 투명 배경 그대로 올린다 |
| `note` | text | "추가 설정" 입력값 (200자까지) |

```jsonc
{
  "name": "낙서 대검",
  "flavor": "…",
  "stats": { "damage": 12, "shotsPerSecond": 1.18, "projectileSpeed": 6.33, "lifetime": 3.91 },
  "variants": [
    { "version": 1, "image": "",        "failed": false },  // 원본 사용
    { "version": 2, "image": "<base64>", "failed": false },
    { "version": 3, "image": "<base64>", "failed": false }
  ],
  "source": "mock",
  "fallback": false,
  "clamp": { "clamped": [], "budgetScaled": false, "rawTotal": 1.122, "finalTotal": 1.121 }
}
```

`failed: true`인 버전은 생성에 실패한 것이고, 클라이언트가 그 칸을 원본으로 채운다.
`fallback: true`면 스탯 생성까지 실패해 기본 무기가 지급된 것이다.
**무엇이 실패해도 200으로 응답한다** — 게임이 멈추지 않는 게 우선이다.

## 밸런스

모델이 내는 숫자를 그대로 믿지 않는다. `app/forge/clamp.py`가 두 단계로 깎는다.

1. 스탯별 범위로 자름 (`STAT_RANGES`)
2. 각 스탯을 0~1로 환산해 더한 값이 `STAT_BUDGET`(2.2)을 넘으면 **비율을 유지한 채** 축소

비율을 유지하는 이유는, 하나만 깎으면 "공격력 높고 느린 둔기" 같은 무기 성격이
망가지기 때문이다.

## 구조

```
app/
  config.py          환경변수 → ServerConfig (키 없으면 목 모드)
  main.py            FastAPI 앱, CORS, /healthz, /forge
  forge/
    schema.py        pydantic 모델, 스탯 범위, 버젯
    clamp.py         범위·버젯 강제 (순수 함수)
    prompt.py        스탯용 1개 + 이미지용 2개 프롬프트
    service.py       스탯 1회 + 이미지 2회 병렬 실행, 폴백 처리
  gemini/
    client.py        generateContent 호출 (httpx)
    mock.py          키 없이 도는 목 구현
tests/               pytest
```

## 알아둘 것

- **이미지 모델 ID(`GEMINI_IMAGE_MODEL`)와 `responseModalities` 동작은 실제 키로 한 번
  확인이 필요하다.** 기본값은 `gemini-2.5-flash-image`로 두었고 env로 교체할 수 있다.
  틀려도 이미지 생성만 실패하고 게임은 원본 그림으로 진행된다.
- 생성 이미지는 흰 배경으로 요청한다. 투명화(누끼)는 클라이언트가 흰색 키잉으로 처리한다.
  음영이 있는 아트에서 거칠면, 그때 서버에 rembg를 붙이는 편이 낫다.
- 저장소가 없다. 생성 결과를 남기려면 `data/`에 파일로 쓰거나 SQLite를 넣는다.
