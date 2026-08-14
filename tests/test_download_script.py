import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.download_raw_data import (
    download_nltk_corpora,
    download_resumable,
    extract_zip_member,
    install_argos_models,
)


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


def test_extract_zip_member_with_target_name(tmp_path):
    zip_path = tmp_path / "corpus.zip"
    payload = "Hello there.\tXin chào.\n".encode("utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("OpenSubtitles.en-vi.en", payload)
    out = tmp_path / "out"
    extract_zip_member(zip_path, out, "OpenSubtitles.en-vi.en", "en-vi.txt.en")
    assert (out / "en-vi.txt.en").read_bytes() == payload


def test_download_opensubtitles_envi_refills_empty_file(tmp_path, monkeypatch):
    """A 0-byte .en file must be treated as missing (the pipeline gate checks
    st_size == 0) — otherwise a truncated download silently skips the corpus."""
    import config.settings as settings
    import scripts.download_raw_data as module

    empty_en = tmp_path / "en-vi.txt.en"
    empty_en.write_bytes(b"")
    vi = tmp_path / "en-vi.txt.vi"
    vi.write_text("Xin chào.\n", encoding="utf-8")

    zip_path = tmp_path / "corpus.zip"
    payload = "Hello there.\n".encode("utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("OpenSubtitles.en-vi.en", payload)
        zf.writestr("OpenSubtitles.en-vi.vi", "Xin chào.\n".encode("utf-8"))

    monkeypatch.setattr(settings, "OPENSUBTITLES_EN", empty_en)
    monkeypatch.setattr(settings, "OPENSUBTITLES_VI", vi)
    monkeypatch.setattr(settings, "OPENSUBTITLES_EN_VI_ZIP", zip_path)
    monkeypatch.setattr(module, "download_resumable", lambda *a, **k: None)

    module.download_opensubtitles_envi()

    assert empty_en.read_bytes() == payload


def test_download_nltk_corpora_uses_local_target_dir(tmp_path):
    with patch("nltk.download") as mock_download:
        mock_download.return_value = True
        res = download_nltk_corpora(target_dir=tmp_path)
        assert mock_download.call_count >= 4
        assert len(res) >= 4
        # Verify download_dir was passed
        for call in mock_download.call_args_list:
            assert "download_dir" in call.kwargs
            assert call.kwargs["download_dir"] == str(tmp_path)


def test_install_argos_models_already_installed():
    with patch("argostranslate.translate.get_installed_languages") as mock_get_lang:
        mock_en = MagicMock()
        mock_en.code = "en"
        mock_vi = MagicMock()
        mock_vi.code = "vi"
        mock_translation = MagicMock()
        mock_translation.to_lang = mock_vi
        mock_en.get_translations.return_value = [mock_translation]
        mock_get_lang.return_value = [mock_en, mock_vi]

        res = install_argos_models()
        assert res is True


def test_install_argos_models_installs_package():
    with patch("argostranslate.translate.get_installed_languages", return_value=[]), \
         patch("argostranslate.package.update_package_index") as mock_update, \
         patch("argostranslate.package.get_available_packages") as mock_get_avail, \
         patch("argostranslate.package.install_from_path") as mock_install:
        pkg = MagicMock()
        pkg.from_code = "en"
        pkg.to_code = "vi"
        pkg.download.return_value = "/fake/path.argosmodel"
        mock_get_avail.return_value = [pkg]

        res = install_argos_models()
        assert res is True
        mock_update.assert_called_once()
        mock_install.assert_called_once_with("/fake/path.argosmodel")

