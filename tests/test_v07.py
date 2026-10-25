"""v0.7.0: 同時ダウンロード・プレビュー解析・プレイヤー用配信サーバー"""
import functools
import http.server
import json
import os
import shutil
import threading
import time
import urllib.request

import pytest

from core import downloader, mediaserver, preview
from core.settings import Settings


# ---------------- プレビュー解析 ----------------
def test_parse_info_video():
    info = {
        "title": "Big Buck Bunny", "channel": "Blender", "duration": 634.5,
        "thumbnail": "https://img/x.jpg",
        "formats": [{"height": 360, "vcodec": "avc1"}, {"height": 1080, "vcodec": "avc1"},
                    {"height": 720, "vcodec": "avc1"}, {"height": None, "vcodec": "none", "acodec": "mp4a"}],
    }
    o = preview.parse_info(info)
    assert o["ok"] and not o["playlist"]
    assert o["title"] == "Big Buck Bunny" and o["uploader"] == "Blender"
    assert o["duration"] == 634.5 and o["thumbnail"] == "https://img/x.jpg"
    assert o["heights"] == [1080, 720, 360] and o["max_height"] == 1080 and o["has_video"]


def test_parse_info_thumbnails_fallback():
    info = {"title": "t", "thumbnails": [{"url": "http://a/1.jpg"}, {"url": "https://a/2.jpg"}], "formats": []}
    assert preview.parse_info(info)["thumbnail"] == "https://a/2.jpg"
    assert preview.parse_info({"title": "t", "thumbnail": "ftp://bad", "formats": []})["thumbnail"] == ""


def test_parse_info_playlist():
    o = preview.parse_info({"_type": "playlist", "title": "My list", "entries": [1, 2, 3]})
    assert o["ok"] and o["playlist"] and o["count"] == 3 and o["title"] == "My list"


def test_quality_options():
    assert preview.quality_options(1080) == [1080, 720, 480, 360, 240, 144]
    assert preview.quality_options(720) == [720, 480, 360, 240, 144]
    assert preview.quality_options(4320 if False else 2160)[0] == 2160
    assert preview.quality_options(None)[0] == 2160


def test_parse_info_bad():
    assert preview.parse_info(None)["ok"] is False
    o = preview.parse_info({"title": "audio only", "formats": [{"acodec": "mp4a", "vcodec": "none"}]})
    assert o["heights"] == [] and o["has_video"] is False


# ---------------- メディアサーバー ----------------
def test_media_server_serves_with_token_and_range(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"0123456789" * 100)   # 1000 bytes
    ms = mediaserver.MediaServer()
    try:
        url = ms.set_file(str(f))
        assert url and url.startswith("http://127.0.0.1:")
        # 全体取得
        data = urllib.request.urlopen(url).read()
        assert data == f.read_bytes()
        # Range取得（シーク）
        req = urllib.request.Request(url, headers={"Range": "bytes=10-19"})
        r = urllib.request.urlopen(req)
        assert r.status == 206 and r.read() == b"0123456789" and r.headers["Content-Range"] == "bytes 10-19/1000"
        # トークンが違うと拒否
        bad = url.split("&t=")[0].split("?")[0] + "?t=wrong"
        try:
            urllib.request.urlopen(bad)
            assert False, "should 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
        # ファイル切り替え
        g = tmp_path / "other.mp4"; g.write_bytes(b"XYZ")
        url2 = ms.set_file(str(g))
        assert urllib.request.urlopen(url2).read() == b"XYZ"
        assert ms.set_file(str(tmp_path / "missing.mp4")) is None
    finally:
        ms.stop()


# ---------------- 同時ダウンロード（並列） ----------------
@pytest.fixture(scope="module")
def slow_server(tmp_path_factory):
    d = tmp_path_factory.mktemp("par")
    import subprocess
    for i in range(6):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=15:duration=2",
                        "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", str(d / f"v{i}.mp4")], check=True)

    class Slow(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def copyfile(self, src, dst):
            while True:
                buf = src.read(16384)
                if not buf:
                    break
                dst.write(buf)
                time.sleep(0.03)       # わざと遅く送る（並列の効果を測れるように）

    handler = functools.partial(Slow, directory=str(d))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{srv.server_address[1]}/", "n": 6}
    srv.shutdown()


def make_engine(settings):
    return downloader.Engine(settings, {
        "ytdlp": lambda: shutil.which("yt-dlp"),
        "ffdir": lambda: os.path.dirname(shutil.which("ffmpeg")),
        "deno": lambda: None,
    })


def run_all(settings, slow_server, tmp_path):
    e = make_engine(settings)
    try:
        ids = [e.add(slow_server["base"] + f"v{i}.mp4", "mp4", "best", "320", str(tmp_path)) for i in range(slow_server["n"])]
        t0 = time.time()
        end = t0 + 120
        while time.time() < end:
            snap = e.snapshot()
            if all(j["status"] in ("done", "error") for j in snap):
                break
            time.sleep(0.1)
        snap = e.snapshot()
        assert all(j["status"] == "done" for j in snap), snap
        return time.time() - t0
    finally:
        e.shutdown()


def test_parallel_is_faster_than_sequential(slow_server, tmp_path):
    s1 = Settings(); s1.set("max_parallel", "1")
    seq = run_all(s1, slow_server, tmp_path / "seq")
    s3 = Settings(); s3.set("max_parallel", "4")
    par = run_all(s3, slow_server, tmp_path / "par")
    assert par < seq * 0.75, (seq, par)       # 並列の方がはっきり速い


def test_parallel_limit_is_respected(slow_server, tmp_path):
    s = Settings(); s.set("max_parallel", "2")
    e = make_engine(s)
    try:
        for i in range(slow_server["n"]):
            e.add(slow_server["base"] + f"v{i}.mp4", "mp4", "best", "320", str(tmp_path))
        peak = 0
        end = time.time() + 60
        while time.time() < end:
            running = sum(1 for j in e.snapshot() if j["status"] == "running")
            peak = max(peak, running)
            if all(j["status"] in ("done", "error") for j in e.snapshot()):
                break
            time.sleep(0.05)
        assert peak <= 2 and peak >= 2, peak        # 同時に最大2本まで
    finally:
        e.shutdown()


def test_settings_max_parallel():
    s = Settings()
    s.set("max_parallel", "4")
    assert Settings().get("max_parallel") == "4"
    for bad in ("0", "5", "two"):
        with pytest.raises(ValueError):
            s.set("max_parallel", bad)


def test_quality_setting_accepts_heights():
    s = Settings()
    for q in ("best", "2160", "1440", "360"):
        s.set("mp4_quality", q)
    with pytest.raises(ValueError):
        s.set("mp4_quality", "999")
