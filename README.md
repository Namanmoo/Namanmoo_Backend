# NaManMoo Backend

무기 만들기(Weapon Forge) API. 플레이어가 그린 그림과 "추가 설정" 텍스트를 받아
**스탯**을 정하고, 요청한 **AI 개입 단계**의 무기 그림 한 장을 돌려준다.

단계는 게임 안 슬라이더로 고른다. **고른 단계만 생성하므로 이미지 API 호출은 최대 1회다.**

| stage | 내용 | 생성 |
| --- | --- | --- |
| 0 | 그린 그림 그대로 (개입 없음) | 안 함 — 이미지 호출 자체가 나가지 않는다 |
| 1 | 형태는 유지하고 선·색만 다듬음 | Gemini 이미지 모델 |
| 2 | 컨셉만 살려 새로 그린 무기 아트 | Gemini 이미지 모델 |

## 실행

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

./run.sh            # http://127.0.0.1:8790
./run.sh --test     # pytest
```

`GEMINI_API_KEY`와 `OPENAI_API_KEY`가 모두 없으면 **목 모드**로 뜬다. 응답 형태가 동일해서 키 없이도
Unity 쪽 단계 선택 흐름을 끝까지 검증할 수 있다. 목은 원본 그림을 실제로 가공해
단계마다 다른 이미지를 만든다 — "그림이 반영되는가"까지 확인된다.

## 제공자가 둘이다

| 하는 일 | 제공자 | 자격증명 |
| --- | --- | --- |
| 스탯 (이름·공격력·연사·탄속·사거리) | Gemini `gemini-flash-latest` | `GEMINI_API_KEY` |
| 무기 그림 1·2단계 | **Cloudflare Workers AI** SD1.5 img2img | `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` |
| " | 또는 OpenAI `/v1/images/edits` | `OPENAI_API_KEY` |

이미지는 **image-to-image여야 한다** — 1단계가 그린 그림의 형태를 지켜야 하므로
text-to-image로는 만들 수 없다.

Cloudflare를 기본으로 두는 이유는 두 가지다. 하루 10,000 뉴런이 무료고(카드 불필요),
`strength` 파라미터로 **단계를 숫자로 강제**할 수 있다 — 1단계 0.35, 2단계 0.80.
다른 제공자에서는 "형태를 바꾸지 마라"를 프롬프트로 부탁해야 한다.

주의: SD 1.5는 영어 프롬프트만 알아듣는다. 그래서 이미지용 프롬프트는 영어로 따로
두고(`build_img2img_prompt`), 플레이어가 쓴 한글 설명은 스탯에만 반영한다.

**왜 나눴나.** Gemini 스탯은 무료 티어에서 잘 돌지만, Gemini 이미지 모델은
무료 할당이 **0**이다. 실측한 오류가 그대로 말해 준다:

```
Quota exceeded for metric: generate_content_free_tier_requests,
limit: 0, model: gemini-2.5-flash-preview-image
```

기다리면 풀리는 레이트 리밋이 아니라 무료 몫이 없는 것이고, `imagen-4.0-*`는
404(신규 사용자 제공 중단)다. OpenAI 이미지 API도 무료 티어가 없어 크레딧이 0이면
`billing_hard_limit_reached`(400)가 돌아온다 — 실제로 그렇게 막혔다.

한쪽 키만 넣어도 그쪽만 동작한다. `/healthz`가 어느 쪽이 살아 있는지 알려준다.
키는 서버에만 두고 클라이언트로 내려보내지 않는다.

## API

### `GET /healthz`
```json
{
  "ok": true,
  "source": "stats=gemini,image=openai",
  "stats": { "provider": "gemini", "model": "gemini-flash-latest" },
  "image": { "provider": "openai", "model": "gpt-image-1.5" }
}
```

### `GET /weapons` — 무기고 목록 (최신순)
```jsonc
{ "weapons": [ { "id": "…", "name": "불꽃 검", "flavor": "…", "stage": 1,
                 "stats": { … }, "createdAt": "2026-07-30T…+00:00" } ] }
```

### `POST /weapons` (multipart) — 무기 저장
`image`(PNG) + `name` `flavor` `stage` `damage` `shotsPerSecond` `projectileSpeed` `lifetime`.
스탯은 여기서도 클램프한다 — 무기고를 통해 밸런스가 새지 않게.

### `GET /weapons/{id}/image` — PNG 바이트
### `DELETE /weapons/{id}`

### `POST /forge` (multipart)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `drawing` | file | PNG. 투명 배경 그대로 올린다 |
| `note` | text | "추가 설정" 입력값 (200자까지) |
| `stage` | text | AI 개입 단계 `0` / `1` / `2` (기본 0) |

```jsonc
{
  "name": "낙서 대검",
  "flavor": "…",
  "stats": { "damage": 12, "shotsPerSecond": 1.18, "projectileSpeed": 6.33, "lifetime": 3.91 },
  "stage": 1,
  "image": "<base64>",     // 0단계이거나 생성 실패면 ""
  "imageFailed": false,
  "source": "mock",
  "fallback": false,
  "clamp": { "clamped": [], "budgetScaled": false, "rawTotal": 1.122, "finalTotal": 1.121 }
}
```

`imageFailed: true`면 생성에 실패한 것이고, 클라이언트가 그린 그림을 그대로 쓴다
(0단계는 실패가 아니므로 `false`다). `fallback: true`면 스탯 생성까지 실패해
기본 무기가 지급된 것이다.
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
    client.py        스탯용 generateContent 호출 (httpx)
    mock.py          키 없이 도는 목 구현
  cloudflare/
    client.py        이미지용 Workers AI img2img 호출 (httpx)
  openai_api/
    client.py        이미지용 /v1/images/edits 호출 (httpx)
tests/               pytest
```

## 알아둘 것

- **스탯은 구조화 출력(`responseSchema`)이 필수다.** 없으면 모델이 마크다운 산문을
  내보내 파싱이 깨진다. `thinkingConfig`는 넣지 마라 — `gemini-flash-latest`가
  400으로 거부한다(실측).
- **OpenAI 이미지 파라미터는 모델마다 다르다.** `background=transparent` 같은 선택
  파라미터를 붙여 한 번 시도하고, 400이면 최소 형태로 재시도한다. 문서상
  `gpt-image-2`는 `input_fidelity`를 거부한다.
- **이미지 손질(`app/forge/image_prep.py`)이 프롬프트보다 중요하다.** 실측으로 얻은 순서다:
  1. 보낼 때 투명 배경을 **흰색으로 눕힌다.** 안 하면 모델이 투명 영역을 검정으로 읽고
     검은 배경을 그대로 보존한다.
  2. 받을 때 가장자리 플러드 필로 **밝은 배경을 지운다.** 프롬프트로 "순백 배경"을
     요구해도 옅은 유령 실루엣과 글자 파편이 계속 낀다.
  3. **떨어진 작은 얼룩을 버린다.** 색이 있는 조각은 배경 제거를 통과해 무기 옆에
     떠다니는 점으로 남는다. 큰 덩어리의 8% 미만만 버려서 일부러 떼어 그린 부품은 살린다.
  4. 손질 후 남은 게 0.5% 미만이면 **생성 실패로 처리한다.** SD가 드물게 거의 빈 이미지를
     내는데, 그대로 넘기면 게임에 보이지 않는 무기가 들어간다(실제로 겪었다).
- 무기고는 `data/weapons/`에 파일로 둔다 — `index.json`(메타데이터) + `<id>.png`(그림).
  프로토라 SQLite 대신 파일이다. 눈으로 열어볼 수 있고 이미지가 그대로 파일이라
  디버깅이 쉽다. `index.json`은 임시 파일에 쓴 뒤 교체해 쓰다가 죽어도 목록이 안 깨진다.
- 계정 개념이 없어 무기고는 하나뿐이다. 여러 사용자를 받으려면 계정 축을 넣어야 한다.
