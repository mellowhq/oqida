import hashlib
import os
import stat
import time
import zipfile

import pytest

from core import paths, tools, updater
from core.updater import AppUpdater, YtdlpUpdater


def wait_state(obj, want, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if obj.snapshot()["state"] in want:
            return obj.snapshot()
        time.sleep(0.05)
    raise AssertionError(f"state stuck at {obj.snapshot()}")


def fake_release(tag="v9.9.9", sha="", asset="OQIDA-9.9.9-Setup.exe"):
    return {"tag_name": tag, "body": "notes", "assets": [
        {"name": asset, "browser_download_url": "http://x/" + asset, "size": 10,
         "digest": ("sha256:" + sha) if sha else None}]}


def test_app_update_flow(monkeypatch, tmp_path):
    payload = b"#!/bin/sh\ntouch \"$(dirname \"$0\")/ran.marker\"\n"
    sha = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(updater, "http_json", lambda url: fake_release(sha=sha))

    def fake_dl(url, dest, progress=None, cancel=None):
        dest.write_bytes(payload)
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR)
        progress(len(payload), len(payload))
        return hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(updater, "download_file", fake_dl)
    monkeypatch.setenv("OQIDA_FORCE_INSTALL", "1")
    exited = []
    u = AppUpdater(on_exit=lambda: exited.append(1))
    u.check()
    s = wait_state(u, {"available", "error", "uptodate"})
    assert s["state"] == "available" and s["latest"] == "9.9.9"
    u.download()
    wait_state(u, {"ready", "error"})
    assert u.snapshot()["state"] == "ready"
    assert u.apply() is True
    marker = paths.tmp_dir() / "ran.marker"
    for _ in range(50):
        if marker.exists() and exited:
            break
        time.sleep(0.1)
    assert marker.exists() and exited


def test_app_update_uptodate_and_error(monkeypatch):
    monkeypatch.setattr(updater, "http_json", lambda url: fake_release(tag="v0.0.1"))
    u = AppUpdater()
    u.check()
    assert wait_state(u, {"uptodate", "error"})["state"] == "uptodate"

    def boom(url):
        raise OSError("offline")
    monkeypatch.setattr(updater, "http_json", boom)
    u.check()
    assert wait_state(u, {"error"})["error"] == "offline"


def test_app_update_checksum_mismatch(monkeypatch):
    monkeypatch.setattr(updater, "http_json", lambda url: fake_release(sha="0" * 64))

    def fake_dl(url, dest, progress=None, cancel=None):
        dest.write_bytes(b"tampered")
        return hashlib.sha256(b"tampered").hexdigest()
    monkeypatch.setattr(updater, "download_file", fake_dl)
    u = AppUpdater()
    u.check()
    wait_state(u, {"available"})
    u.download()
    s = wait_state(u, {"error", "ready"})
    assert s["state"] == "error" and "checksum" in s["error"]


def test_apply_refused_in_dev_mode(monkeypatch):
    monkeypatch.delenv("OQIDA_FORCE_INSTALL", raising=False)
    monkeypatch.setattr(updater, "http_json", lambda url: fake_release())
    monkeypatch.setattr(updater, "download_file",
                        lambda url, dest, progress=None, cancel=None: (dest.write_bytes(b"x"), hashlib.sha256(b"x").hexdigest())[1])
    u = AppUpdater()
    u.check(); wait_state(u, {"available"})
    u.download(); wait_state(u, {"ready"})
    assert u.apply() is False
    assert u.snapshot()["error"] == "dev_mode"


def test_zip_extraction_ffmpeg(monkeypatch, tmp_path):
    z = tmp_path / "ff.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ffmpeg-master/bin/ffmpeg.exe", b"FF")
        zf.writestr("ffmpeg-master/bin/ffprobe.exe", b"FP")
        zf.writestr("ffmpeg-master/bin/ffplay.exe", b"NO")
        zf.writestr("ffmpeg-master/LICENSE.txt", b"L")
    monkeypatch.setenv("OQIDA_ALLOW_FETCH", "1")
    monkeypatch.setattr(tools, "FFMPEG_URL", z.as_uri())
    tools.fetch("ffmpeg")
    b = paths.bin_dir()
    assert (b / "ffmpeg.exe").read_bytes() == b"FF" and (b / "ffprobe.exe").read_bytes() == b"FP"
    assert not (b / "ffplay.exe").exists() and not list(b.glob("*.new"))


def test_zip_missing_member_fails(monkeypatch, tmp_path):
    z = tmp_path / "d.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", b"x")
    monkeypatch.setenv("OQIDA_ALLOW_FETCH", "1")
    monkeypatch.setattr(tools, "DENO_URL", z.as_uri())
    with pytest.raises(RuntimeError):
        tools.fetch("deno")


def test_ytdlp_checksum_verified(monkeypatch):
    monkeypatch.setenv("OQIDA_ALLOW_FETCH", "1")
    monkeypatch.delenv("OQIDA_YTDLP", raising=False)
    monkeypatch.setattr(tools, "exe_version", lambda p: "2099.01.01")          # ダウンロードした物が動く、という前提にする
    monkeypatch.setattr(tools, "http_json", lambda url: {"tag_name": "2099.01.01", "assets": [
        {"name": "yt-dlp.exe", "browser_download_url": "http://x/yt-dlp.exe", "digest": "sha256:" + "a" * 64}]})

    def bad_dl(url, dest, progress=None, cancel=None):
        dest.write_bytes(b"evil")
        return "b" * 64
    monkeypatch.setattr(tools, "download_file", bad_dl)
    with pytest.raises(RuntimeError):
        tools._fetch_ytdlp(None, None)
    assert not tools.ytdlp_bin_path().exists()

    good = hashlib.sha256(b"ok").hexdigest()
    monkeypatch.setattr(tools, "http_json", lambda url: {"tag_name": "2099.01.01", "assets": [
        {"name": "yt-dlp.exe", "browser_download_url": "http://x/yt-dlp.exe", "digest": "sha256:" + good}]})
    monkeypatch.setattr(tools, "download_file",
                        lambda url, dest, progress=None, cancel=None: (dest.write_bytes(b"ok"), good)[1])
    tools._fetch_ytdlp(None, None)
    assert tools.ytdlp_bin_path().read_bytes() == b"ok"


def test_ytdlp_updater_waits_while_busy(monkeypatch):
    busy = {"v": True}
    monkeypatch.setattr(tools, "check_ytdlp_update", lambda: {"current": "1", "latest": "2", "available": True})
    done = []
    monkeypatch.setattr(tools, "update_ytdlp", lambda progress=None: done.append(1))
    monkeypatch.setattr(tools, "ytdlp_version", lambda: "2")
    y = YtdlpUpdater(lambda: busy["v"])
    y.check(auto_apply=True)
    wait_state(y, {"waiting"})
    assert not done
    busy["v"] = False
    assert wait_state(y, {"updated", "error"}, 5)["state"] == "updated" and done
