"""日本語を含むフォルダ名・ファイル名でも、完成パスを正しく受け取って done になること"""
import functools
import http.server
import os
import shutil
import threading
import time
import urllib.parse

import pytest

from core import downloader
from core.settings import Settings


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    import subprocess
    # 日本語ファイル名の動画（タイトルが日本語になる）
    name = "ラップスター 2026 #4.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-crf", "30",
                    "-c:a", "aac", "-shortest", "-pix_fmt", "yuv420p", str(d / name)], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/" + urllib.parse.quote(name)
    srv.shutdown()


@pytest.fixture
def engine():
    e = downloader.Engine(Settings(), {
        "ytdlp": lambda: shutil.which("yt-dlp"),
        "ffdir": lambda: os.path.dirname(shutil.which("ffmpeg")),
        "deno": lambda: None,
    })
    yield e
    e.shutdown()


def wait(e, jid, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in e.snapshot() if x["id"] == jid)
        if j["status"] in ("done", "error", "canceled"):
            return j
        time.sleep(0.1)
    raise AssertionError("timeout")


def test_build_args_uses_donefile_and_utf8():
    a = downloader.build_args({"fmt": "mp4", "quality": "best", "bitrate": "320", "url": "https://x/y", "section": None,
                               "save_thumb": False, "size_limit": 0}, "/out", "yt", "/ff", None, donefile="/tmp/done.txt")
    assert a[a.index("--encoding") + 1] == "utf-8"
    assert "--print-to-file" in a and a[a.index("--print-to-file") + 1] == "after_move:%(filepath)s"
    assert a[a.index("--print-to-file") + 2] == "/tmp/done.txt"
    assert any("OQIDA_DONE|" in x for x in a)       # 念のため標準出力にもフォールバックで出す
    # donefile 未指定なら標準出力のみ
    b = downloader.build_args({"fmt": "mp4", "quality": "best", "bitrate": "320", "url": "https://x/y", "section": None,
                               "save_thumb": False, "size_limit": 0}, "/out", "yt", "/ff", None)
    assert "--print-to-file" not in b and any("OQIDA_DONE|" in x for x in b)


def test_download_to_japanese_folder_with_japanese_title(engine, server, tmp_path):
    outdir = tmp_path / "oqida 保存先"          # スペース＋日本語を含むフォルダ
    jid = engine.add(server, "mp4", "best", "320", str(outdir))
    j = wait(engine, jid)
    assert j["status"] == "done", j             # 以前はここが error（output file is missing）になっていた
    assert j["filepath"] and os.path.isfile(j["filepath"])     # 受け取ったパスが実在する
    assert os.path.dirname(j["filepath"]) == str(outdir)
    assert "ラップスター" in os.path.basename(j["filepath"])    # 日本語タイトルが文字化けせず残る
    assert j["size"] == os.path.getsize(j["filepath"]) > 1000
    assert not [f for f in os.listdir(__import__("core.paths", fromlist=["tmp_dir"]).tmp_dir()) if f.startswith("done")]  # 受け取り用ファイルは残さない


def test_japanese_to_mp3_and_gif(engine, server, tmp_path):
    out = tmp_path / "音楽 フォルダ"
    jm = wait(engine, engine.add(server, "mp3", "best", "192", str(out)))
    assert jm["status"] == "done" and jm["filepath"].endswith(".mp3") and os.path.isfile(jm["filepath"])
    jg = wait(engine, engine.add(server, "gif", "best", "320", str(out),
                                 gif={"start": "0", "length": "1", "width": 320, "fps": 10}))
    assert jg["status"] == "done" and jg["filepath"].endswith(".gif") and os.path.isfile(jg["filepath"])
