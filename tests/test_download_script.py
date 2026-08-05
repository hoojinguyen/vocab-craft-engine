import io
import zipfile
from pathlib import Path

from scripts.download_raw_data import download_resumable, extract_zip_member


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_download_resumable_sends_range_and_appends(tmp_path, monkeypatch):
    dest = tmp_path / "corpus.en"
    dest.write_bytes(b"partial ")

    captured = {}

    def fake_open(request):
        captured["range"] = request.get_header("Range")
        return _FakeResp(b"rest of payload")

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr("urllib.request.Request", lambda url, headers=None: type(
        "Req", (), {"get_header": lambda self, k: (headers or {}).get(k), "full_url": url})())

    download_resumable("https://example.com/corpus.en", dest)

    assert captured["range"] == "bytes=8-"          # resumes after 8 existing bytes
    assert dest.read_bytes() == b"partial rest of payload"


def test_extract_zip_member(tmp_path):
    zip_path = tmp_path / "corpus.zip"
    payload = "en\tvi\nHello there.\tXin chào.\n".encode("utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("en-vi.txt.en", payload)
    out = tmp_path / "out"
    extract_zip_member(zip_path, out, "en-vi.txt.en")
    assert (out / "en-vi.txt.en").read_bytes() == payload
