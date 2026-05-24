import pytest

from ff_calendar_toolkit.telegram import TelegramError, TelegramSender


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def now_fn(self) -> float:
        return self.now

    def sleep_fn(self, secs: float) -> None:
        self.sleeps.append(secs)
        self.now += secs


def _capture_post():
    calls = []

    def fake(url, payload):
        calls.append((url, payload.decode()))

    return calls, fake


def test_token_required():
    with pytest.raises(TelegramError):
        TelegramSender(bot_token="")


def test_first_send_does_not_wait_subsequent_does():
    clock = FakeClock()
    calls, fake_post = _capture_post()
    s = TelegramSender(
        bot_token="t", per_chat_interval_secs=2.0,
        now_fn=clock.now_fn, sleep_fn=clock.sleep_fn, http_post=fake_post,
    )

    s.send("123", "first")
    assert clock.sleeps == []
    assert len(calls) == 1

    s.send("123", "second")
    assert clock.sleeps == [2.0]
    assert len(calls) == 2


def test_separate_chats_have_independent_buckets():
    clock = FakeClock()
    _, fake_post = _capture_post()
    s = TelegramSender(
        bot_token="t", per_chat_interval_secs=5.0,
        now_fn=clock.now_fn, sleep_fn=clock.sleep_fn, http_post=fake_post,
    )

    s.send("A", "x")
    s.send("B", "y")  # different chat → no wait
    assert clock.sleeps == []


def test_url_and_payload_shape():
    calls, fake_post = _capture_post()
    s = TelegramSender(
        bot_token="TKN", per_chat_interval_secs=0,
        now_fn=lambda: 0.0, sleep_fn=lambda _s: None, http_post=fake_post,
    )
    s.send("99", "hello world", parse_mode="MarkdownV2")
    url, body = calls[0]
    assert url == "https://api.telegram.org/botTKN/sendMessage"
    assert "chat_id=99" in body
    assert "text=hello+world" in body
    assert "parse_mode=MarkdownV2" in body


def test_empty_chat_id_raises():
    s = TelegramSender(bot_token="t", per_chat_interval_secs=0, http_post=lambda u, p: None)
    with pytest.raises(TelegramError):
        s.send("", "hi")


def test_from_env_reads_token_and_interval(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_PER_CHAT_INTERVAL_SECS", "0.5")
    s = TelegramSender.from_env()
    assert s.bot_token == "abc"
    assert s.per_chat_interval_secs == 0.5


def test_from_env_requires_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(TelegramError):
        TelegramSender.from_env()
