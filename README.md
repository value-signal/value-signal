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
uv run python -m pipeline.run <init-db|collect|extract|score|alert|all>
uv run pytest
uv run ruff check .
```

`init-db` 외의 배치 단계는 아직 구현되지 않았습니다.
