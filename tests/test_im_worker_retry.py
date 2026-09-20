import asyncio
from types import SimpleNamespace

from app.im import worker


def test_retry_delay_is_exponential_bounded_and_jittered():
    assert worker.retry_delay_seconds(1, random_value=0.5) == 2
    assert worker.retry_delay_seconds(3, random_value=0.5) == 8
    assert worker.retry_delay_seconds(20, cap=30, random_value=0.5) == 30
    assert worker.retry_delay_seconds(1, random_value=0) == 1.6
    assert worker.retry_delay_seconds(1, random_value=1) == 2.4


def test_permanent_http_error_is_not_retryable():
    exc = RuntimeError("forbidden")
    exc.status_code = 403
    assert worker._is_retryable_delivery_error(exc) is False


def test_rate_limit_and_server_errors_are_retryable():
    for status in (429, 500, 503):
        exc = RuntimeError(str(status))
        exc.response = SimpleNamespace(status_code=status)
        assert worker._is_retryable_delivery_error(exc) is True


def test_delivery_moves_to_dead_after_max_attempts(monkeypatch):
    row = {
        "id": "outbox_1",
        "channel_id": "chan_1",
        "receive_id": "oc_1",
        "receive_id_type": "chat_id",
        "content": "answer",
        "reply_to_message_id": "om_1",
        "attempts": 2,
    }
    captured = {}

    class FailingProvider:
        async def send(self, message):
            raise TimeoutError("timeout")

    monkeypatch.setenv("IM_OUTBOX_MAX_ATTEMPTS", "2")
    monkeypatch.setattr(worker.jobs, "claim_outbox", lambda *args, **kwargs: row)

    def retry(outbox_id, worker_id, *, error, retry_at):
        captured.update(error=error, retry_at=retry_at)
        return True

    monkeypatch.setattr(worker.jobs, "retry_outbox", retry)
    assert asyncio.run(worker.deliver_outbox_once(provider=FailingProvider())) is False
    assert captured["retry_at"] is None
    assert "TimeoutError" in captured["error"]
