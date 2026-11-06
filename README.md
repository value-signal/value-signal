# Value Signal

기업이 공시로 약속한 기업가치 제고 계획을 AI가 숫자로 읽고, DART 실적으로 이행 여부를 채점하는 서비스입니다.

## 핵심 원칙

- 목표 추출과 질문 답변만 LLM이 맡습니다.
- 이행률은 `pipeline/scoring`의 코드만 계산하며, 이 패키지에서는 LLM을 호출하지 않습니다.
- 모든 결과는 원문 위치와 함께 저장합니다. 근거가 없으면 `확인 불가`로 표시합니다.
- 웹은 배치가 만든 DB만 읽습니다. 실시간 LLM 호출은 근거 Q&A뿐입니다.

## LLM 장애 처리

| 상황 | 처리 |
|---|---|
| 분당 한도 초과 | 안내된 시간만큼 기다린 뒤 재시도 |
| 일일 한도 초과 | 기다리지 않고 예비 모델로 전환 |
| 서버 오류, 시간 초과, 빈 응답, 깨진 JSON | 대기 시간을 늘리며 재시도 후 예비 모델로 전환 |
| 잘못된 키, 모델 이름 | 재시도 없이 오류 발생 |
| 모든 모델 실패 | `LLMUnavailableError` 발생 |

모든 모델이 실패하면 KPI 추출은 해당 공시를 되돌리고 멈추며, 다시 실행하면 그 공시부터 이어서 처리합니다. API는 503과 안내 문구를 반환합니다. 대시보드는 DB만 읽으므로 영향을 받지 않습니다.

## 근거 Q&A

- 기업별 채점 결과와 최신 계획 공시만 근거로 답합니다.
- LLM이 쓴 숫자가 근거에 없거나 출처가 없으면 답을 버리고 `확인 불가`로 답합니다.
- 같은 질문은 저장된 답을 재사용합니다. 근거 데이터가 바뀌면 새로 답합니다.
- 새 질문은 하루 `QA_DAILY_LIMIT`회까지 처리합니다.

## 구조

```text
pipeline/
  collect/   공시 목록·원문·실적 수집
  extract/   원문 분할, LLM KPI 추출, 인용 검증
  scoring/   이행률 계산
  alerts/    변화 감지, 이메일 발송
  run.py     배치 실행
api/         FastAPI 서버
web/         React 대시보드
db/          스키마, 로컬 SQLite
data/        대상 기업 목록, 원문 캐시
evals/       정답 KPI, 추출 정확도 측정
tests/       테스트
```

## 시작하기

필요한 도구: [uv](https://docs.astral.sh/uv/), Node.js 22 이상

```bash
cp .env.example .env        # DART_API_KEY 입력
uv sync
uv run python -m pipeline.run init-db
```

서버 두 개를 각각 실행합니다.

```bash
uv run uvicorn api.main:app --reload
```

```bash
cd web
npm install
npm run dev
```

## 명령어

```bash
uv run python -m pipeline.run <init-db|collect|extract|review|claims|score|alert|all>
uv run pytest
uv run ruff check .
```

`alert` 단계는 아직 구현되지 않았습니다.

## 회사 자기평가 비교

`claims` 단계에서 LLM이 이행현황 공시의 실적 표현을 뽑고, `score` 단계에서 코드가 같은 연도 표준 실적과 비교합니다. 차이가 있으면 회사가 밝힌 기준과 함께 보여줍니다. 차이는 기준 차이일 수 있으며 공시 오류를 뜻하지 않습니다.

## 데이터 파일

| 파일 | 내용 |
|---|---|
| `data/target_companies.csv` | 채점 대상 기업 |
| `data/kpi_reviews.csv` | 사람이 검수한 KPI 수정·제외 내역. `review` 단계에서 반영 |
| `data/claim_reviews.csv` | 실적이 아니라고 판단해 제외한 회사 표현 |
| `data/low_pbr_list.csv` | 2026.11.2 공표 저PBR 151개사 (KIND) |
| `data/pbr_plan_filers.csv` | 공시 제목에 PBR 개선 계획이 표시된 62개사 |
| `evals/gold_kpis.csv` | 추출 정확도 평가용 정답 |

`on_low_pbr_list`가 0인 기업에는 공표 면제 34개사가 포함될 수 있지만, 면제 명단은 공개되지 않아 구분할 수 없습니다.

## 채점 규칙

- 목표를 넘으면 `달성`, 달성률이 기간 경과율보다 20%p 이상 뒤처지거나 기한까지 미달이면 `주의`, 그 외는 `진행 중`입니다.
- 회사 기준이 표준 지표와 다르거나 계산할 수 없으면 `확인 불가`입니다. 지난해 값을 대신 쓰지 않습니다.
- 주주환원율은 `(현금배당 총액 + 자기주식 취득액) / 지배주주 순이익`이며, 회사 정의와 다를 수 있습니다.
