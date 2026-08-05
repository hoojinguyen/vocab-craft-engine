import json
import time

from src.nlp.tatoeba_api import TatoebaApiClient


def test_fetch_parses_results():
    payload = {
        "data": [
            {"text": "The cat sleeps.", "translations": [{"text": "Con mèo ngủ.", "lang": "vie"}]},
            {"text": "A dog barks.", "translations": []},
        ],
        "paging": {"total": 2, "has_next": False, "next": None},
    }

    class FakeResp:
        def read(self): return json.dumps(payload).encode()
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    class FakeOpener:
        def __init__(self):
            self.calls = 0
        def open(self, request):
            self.calls += 1
            return FakeResp()

    opener = FakeOpener()
    client = TatoebaApiClient(opener=opener.open, min_delay=0.0)
    rows = client.fetch_sentences_for_word("cat", limit=10)

    assert len(rows) == 1
    assert rows[0]["text_en"] == "The cat sleeps."
    assert rows[0]["text_vi"] == "Con mèo ngủ."
    assert rows[0]["source"] == "Tatoeba"


def test_rate_limited():
    calls = []

    def fake_open(request):
        calls.append(time.monotonic())
        class R:
            def read(self): return json.dumps({"data": []}).encode()
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        return R()

    client = TatoebaApiClient(opener=fake_open, min_delay=0.2)
    client.fetch_sentences_for_word("a", limit=1)
    client.fetch_sentences_for_word("b", limit=1)
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.15


def test_cache_hit_skips_network():
    payload = {"data": [{"text": "The cat sleeps.", "translations": [{"text": "Con mèo ngủ.", "lang": "vie"}]}]}

    class FakeResp:
        def read(self): return json.dumps(payload).encode()
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    class FakeOpener:
        def __init__(self):
            self.calls = 0
        def open(self, request):
            self.calls += 1
            return FakeResp()

    opener = FakeOpener()
    client = TatoebaApiClient(opener=opener.open, min_delay=0.0)
    client.fetch_sentences_for_word("cat", limit=10)
    client.fetch_sentences_for_word("cat", limit=10)

    assert opener.calls == 1


def test_api_error_returns_empty():
    def fake_open(request):
        raise OSError("boom")

    client = TatoebaApiClient(opener=fake_open, min_delay=0.0)
    rows = client.fetch_sentences_for_word("cat", limit=10)

    assert rows == []
