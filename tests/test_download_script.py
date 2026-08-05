import io
import zipfile
from pathlib import Path

from scripts.download_raw_data import download_resumable, extract_zip_member


class _FakeResp(io.BytesIO):
    def __init__(self, data, status=206):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _fake_request(url, headers=None):
    return type("Req", (), {"get_header": lambda self, k: (headers or {}).get(k), "full_url": url})()


def _patch_download(monkeypatch, fake_open):
    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr("urllib.request.Request", _fake_request)


def test_download_resumable_sends_range_and_appends(tmp_path, monkeypatch):
    dest = tmp_path / "corpus.en"
    dest.write_bytes(b"partial ")

    captured = {}

    def fake_open(request):
        captured["range"] = request.get_header("Range")
        return _FakeResp(b"rest of payload", status=206)

    _patch_download(monkeypatch, fake_open)

    download_resumable("https://example.com/corpus.en", dest)

    assert captured["range"] == "bytes=8-"          # resumes after 8 existing bytes
    assert dest.read_bytes() == b"partial rest of payload"


def test_download_resumable_truncates_on_200_full_body(tmp_path, monkeypatch):
    dest = tmp_path / "corpus.en"
    dest.write_bytes(b"partial ")

    def fake_open(request):
        return _FakeResp(b"complete payload", status=200)

    _patch_download(monkeypatch, fake_open)

    download_resumable("https://example.com/corpus.en", dest)

    assert dest.read_bytes() == b"complete payload"   # no duplicate partial


def test_extract_zip_member(tmp_path):
    zip_path = tmp_path / "corpus.zip"
    payload = "en\tvi\nHello there.\tXin chào.\n".encode("utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("en-vi.txt.en", payload)
    out = tmp_path / "out"
    extract_zip_member(zip_path, out, "en-vi.txt.en")
    assert (out / "en-vi.txt.en").read_bytes() == payload
