import json
import time
from collections.abc import Callable, Sequence
from typing import Literal, Protocol, TypeVar

import httpx
import httpx2
from google import genai
from google.genai import errors, types

from pipeline.config import settings

T = TypeVar("T")
Reason = Literal["quota", "timeout", "server", "empty_response"]

RETRYABLE_SERVER_CODES = {500, 502, 503, 504}
# SDK는 httpx2가 설치되어 있으면 httpx2를 쓴다.
TRANSPORT_ERRORS = (httpx.TransportError, httpx2.TransportError)


class LLMUnavailableError(Exception):
    """재시도와 예비 모델까지 실패했다. 호출부는 답을 지어내지 말고 중단하거나 안내한다."""

    def __init__(self, reason: Reason, retry_after: float | None = None) -> None:
        super().__init__(f"LLM unavailable: {reason}")
        self.reason = reason
        self.retry_after = retry_after


class LLMClient(Protocol):
    """LLM 제공사 교체 지점."""

    def complete_json(self, system: str, user: str, schema: dict) -> dict: ...

    def complete_text(self, system: str, user: str) -> str: ...


def _quota_details(error: errors.APIError) -> list[dict]:
    body = error.details if isinstance(error.details, dict) else {}
    details = body.get("error", {}).get("details", [])
    return [item for item in details if isinstance(item, dict)]


def _quota_wait(error: errors.APIError, backoff: float) -> float | None:
    """분당 한도면 대기 시간을, 일일 한도처럼 기다려도 풀리지 않으면 None을 반환한다."""
    details = _quota_details(error)
    if "PerDay" in json.dumps(details):
        return None
    for item in details:
        delay = item.get("retryDelay")
        if delay:
            return float(delay.removesuffix("s"))
    return backoff


class GeminiClient:
    def __init__(
        self,
        client,
        models: Sequence[str],
        max_wait_seconds: float,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.models = models
        self.max_wait_seconds = max_wait_seconds
        self.max_attempts = max_attempts
        self.sleep = sleep

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        return self._generate(user, config, json.loads)

    def complete_text(self, system: str, user: str) -> str:
        config = types.GenerateContentConfig(system_instruction=system)
        return self._generate(user, config, str)

    def _generate(self, user: str, config, parse: Callable[[str], T]) -> T:
        failure = None
        for model in self.models:
            try:
                return self._call_model(model, user, config, parse)
            except LLMUnavailableError as error:
                failure = error
        raise failure

    def _call_model(self, model: str, user: str, config, parse: Callable[[str], T]) -> T:
        for attempt in range(self.max_attempts):
            backoff = 2.0**attempt
            try:
                response = self.client.models.generate_content(
                    model=model, contents=user, config=config
                )
                if not response.text or not response.text.strip():
                    raise ValueError("empty response")
                return parse(response.text)
            except errors.APIError as error:
                # 잘못된 키나 모델 이름은 재시도해도 소용없으니 그대로 올린다.
                if error.code == 429:
                    failure = LLMUnavailableError("quota", _quota_wait(error, backoff))
                elif error.code in RETRYABLE_SERVER_CODES:
                    failure = LLMUnavailableError("server", backoff)
                else:
                    raise
            except TRANSPORT_ERRORS:
                failure = LLMUnavailableError("timeout", backoff)
            except ValueError:  # 빈 응답 또는 깨진 JSON
                failure = LLMUnavailableError("empty_response", backoff)

            wait = failure.retry_after
            is_last_attempt = attempt == self.max_attempts - 1
            if wait is None or wait > self.max_wait_seconds or is_last_attempt:
                break
            self.sleep(wait)
        raise failure


def create_llm_client(
    max_wait_seconds: float = 60, timeout_seconds: int = 120, max_attempts: int = 3
) -> GeminiClient:
    """배치는 기본값을 쓴다. 사용자가 기다리는 Q&A는 (5, 10, 1)처럼 빨리 포기하게 넘긴다."""
    client = genai.Client(
        api_key=settings.llm_api_key,
        http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
    )
    models = [m for m in (settings.llm_model, settings.llm_fallback_model) if m]
    return GeminiClient(client, models, max_wait_seconds, max_attempts)
