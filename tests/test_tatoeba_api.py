import json

from src.nlp.tatoeba_api import TatoebaApiClient


def test_fetch_parses_results(monkeypatch):
    payload = {
        "results": [
            {"text": "The cat sleeps.", "translations": [[{"text": "Con mèo ngủ."}]]},
            {"text": "A dog barks.", "translations": [[]]},
        ]
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
    client = TatoebaApiClient(open=opener.open, min_delay=0.0)
    rows = client.fetch_sentences_for_word("cat", limit=10)

    assert len(rows) == 1
    assert rows[0]["text_en"] == "The cat sleeps."
    assert rows[0]["text_vi"] == "Con mèo ngủ."
    assert rows[0]["source"] == "Tatoeba"


def test_rate_limited(monkeypatch):
    import time
    calls = []

    def fake_open(request):
        calls.append(time.time())
        class R:
            def read(self): return json.dumps({"results": []}).encode()
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        return R()

    client = TatoebaApiClient(open=fake_open, min_delay=0.2)
    client.fetch_sentences_for_word("a", limit=1)
    client.fetch_sentences_for_word("b", limit=1)
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.15
