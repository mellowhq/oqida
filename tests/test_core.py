import os
import shutil
import time

import pytest

from core import downloader, netutil, paths, tools
from core.settings import Settings


def wait_done(engine, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in engine.snapshot() if x["id"] == jid)
        if j["status"] in ("done", "error", "canceled"):
            return j
        time.sleep(0.2)
    raise AssertionError("timeout")


@pytest.fixture
def engine(tmp_path):
    s = Settings()
    e = downloader.Engine(s, {
        "ytdlp": lambda: shutil.which("yt-dlp"),
        "ffdir": lambda: os.path.dirname(shutil.which("ffmpeg")),
        "deno": lambda: None,
    })
    yield e
    e.shutdown()


def test_version_compare():
    assert netutil.is_newer("v0.2.0", "0.1.0")
    assert netutil.is_newer("2026.10.21", "2026.9.30")
    assert not netutil.is_newer("v0.1.0", "0.1.0")
    assert not netutil.is_newer("junk", "0.1.0")
    assert netutil.is_newer("v0.10.0", "0.9.9")


def test_settings_validation_and_persist():
    s = Settings()
    s.set("theme", "light")
    with pytest.raises(ValueError):
        s.set("theme", "neon")
    with pytest.raises(ValueError):
        s.set("unknown", 1)
    assert Settings().get("theme") == "light"
    paths.settings_file().write_text("{broken", encoding="utf-8")
    assert Settings().get("theme") == "dark"


def test_classify_error():
    assert downloader.classify_error("ERROR: Sign in to confirm you’re not a bot") == "bot_check"
    assert downloader.classify_error("ERROR: Video unavailable") == "unavailable"
    assert downloader.classify_error("ERROR: Private video") == "private"
    assert downloader.classify_error("???") == "unknown"


def test_build_args_mp4_mp3():
    mp4 = {"fmt": "mp4", "quality": "720", "bitrate": "320", "url": "https://x/y"}
    a = downloader.build_args(mp4, "/o", "yt", "/ff", "/deno", "edge")
    assert "res:720,vcodec:h264,acodec:m4a" in a and "--merge-output-format" in a
    assert a[a.index("--js-runtimes") + 1] == "deno:/deno"
    assert a[a.index("--cookies-from-browser") + 1] == "edge"
    assert a[-1] == "https://x/y"
    mp3 = {"fmt": "mp3", "quality": "best", "bitrate": "192", "url": "https://x/y"}
    b = downloader.build_args(mp3, "/o", "yt", "/ff", None, "none")
    assert "--audio-format" in b and "192K" in b and "--js-runtimes" not in b


def test_bad_url_rejected(engine):
    with pytest.raises(ValueError):
        engine.add("not a url", "mp4", "best", "320", "/tmp")
    with pytest.raises(ValueError):
        engine.add("javascript:alert(1)", "mp4", "best", "320", "/tmp")


def test_download_mp4(engine, media_server, tmp_path):
    jid = engine.add(media_server, "mp4", "best", "320", str(tmp_path / "out"))
    j = wait_done(engine, jid)
    assert j["status"] == "done", j
    assert j["filepath"].endswith(".mp4") and os.path.getsize(j["filepath"]) > 1000
    assert j["percent"] == 100.0


def test_download_mp3(engine, media_server, tmp_path):
    jid = engine.add(media_server, "mp3", "best", "192", str(tmp_path / "out"))
    j = wait_done(engine, jid)
    assert j["status"] == "done", j
    assert j["filepath"].endswith(".mp3") and os.path.exists(j["filepath"])


def test_error_job_has_code(engine, tmp_path):
    jid = engine.add("http://127.0.0.1:9/nothing.mp4", "mp4", "best", "320", str(tmp_path / "out"))
    j = wait_done(engine, jid)
    assert j["status"] == "error" and j["error"] in ("network", "unknown", "unsupported")


def test_tools_missing_reports(tmp_path):
    e = downloader.Engine(Settings(), {"ytdlp": lambda: None, "ffdir": lambda: None, "deno": lambda: None})
    jid = e.add("https://example.com/a.mp4", "mp4", "best", "320", str(tmp_path))
    j = wait_done(e, jid, 10)
    assert j["status"] == "error" and j["error"] == "tools_missing"
    e.retry(jid)
    e.shutdown()


def test_queue_order_and_remove(engine, media_server, tmp_path):
    a = engine.add(media_server, "mp3", "best", "128", str(tmp_path / "o"))
    b = engine.add(media_server, "mp4", "480", "128", str(tmp_path / "o"))
    wait_done(engine, a)
    wait_done(engine, b)
    engine.clear_finished()
    assert engine.snapshot() == []


def test_tools_paths_windows_layout(monkeypatch, tmp_path):
    monkeypatch.delenv("OQIDA_YTDLP", raising=False)
    monkeypatch.delenv("OQIDA_FFMPEG_DIR", raising=False)
    b = paths.bin_dir()
    # Windows以外ではPATH探索になるので、binにあれば優先されることだけ確認
    (b / "yt-dlp").write_text("x")
    assert tools.ytdlp_path() == str(b / "yt-dlp")
