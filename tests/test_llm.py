from types import SimpleNamespace

import httpx
import httpx2
import pytest
from google.genai import errors

from pipeline.llm import GeminiClient, LLMUnavailableError

MINUTE_QUOTA = errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
    {"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
    {"retryDelay": "7s"},
]}})
DAILY_QUOTA = errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
    {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
    {"retryDelay": "7s"},
]}})
SERVER_ERROR = errors.ServerError(503, {"error": {"status": "UNAVAILABLE"}})
INVALID_KEY = errors.ClientError(401, {"error": {"status": "UNAUTHENTICATED"}})


def reply(text):
    return SimpleNamespace(text=text)


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.called_models = []

    def generate_content(self, model, contents, config):
        self.called_models.append(model)
        outcomes = self.outcomes[model]
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(outcomes, max_wait_seconds=60):
    models = FakeModels(outcomes)
    waits = []
    client = GeminiClient(
        SimpleNamespace(models=models),
        list(outcomes),
        max_wait_seconds,
        sleep=waits.append,
    )
    return client, models, waits


def test_minute_quota_waits_for_server_delay_then_retries():
    client, _, waits = make_client({"main": [MINUTE_QUOTA, reply("답변")]})

    assert client.complete_text("system", "user") == "답변"
    assert waits == [7]


def test_daily_quota_switches_to_fallback_without_waiting():
    client, models, waits = make_client({"main": [DAILY_QUOTA], "backup": [reply("답변")]})

    assert client.complete_text("system", "user") == "답변"
    assert models.called_models == ["main", "backup"]
    assert waits == []


def test_delay_over_limit_switches_to_fallback_without_waiting():
    client, models, waits = make_client(
        {"main": [MINUTE_QUOTA], "backup": [reply("답변")]}, max_wait_seconds=5
    )

    assert client.complete_text("system", "user") == "답변"
    assert models.called_models == ["main", "backup"]
    assert waits == []


def test_all_models_exhausted_raises_unavailable():
    client, _, _ = make_client({"main": [DAILY_QUOTA], "backup": [DAILY_QUOTA]})

    with pytest.raises(LLMUnavailableError) as caught:
        client.complete_text("system", "user")
    assert caught.value.reason == "quota"
    assert caught.value.retry_after is None


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (SERVER_ERROR, "server"),
        (httpx.ReadTimeout("timeout"), "timeout"),
        (httpx2.ReadTimeout("timeout"), "timeout"),
        (httpx2.ConnectError("connect"), "timeout"),
        (reply(None), "empty_response"),
        (reply("   "), "empty_response"),
    ],
)
def test_transient_failures_back_off_then_raise(outcome, reason):
    client, models, waits = make_client({"main": [outcome]})

    with pytest.raises(LLMUnavailableError) as caught:
        client.complete_text("system", "user")
    assert caught.value.reason == reason
    assert len(models.called_models) == 3
    assert waits == [1, 2]


def test_broken_json_is_retried():
    client, _, _ = make_client({"main": [reply("{깨진"), reply('{"ok": true}')]})

    assert client.complete_json("system", "user", {"type": "object"}) == {"ok": True}


def test_invalid_key_is_not_hidden_or_retried():
    client, models, _ = make_client({"main": [INVALID_KEY], "backup": [reply("답변")]})

    with pytest.raises(errors.ClientError):
        client.complete_text("system", "user")
    assert models.called_models == ["main"]
