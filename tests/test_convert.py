"""ファイル変換（ローカル動画/音声 → 別形式）と、GIF区間オフのテスト"""
import os
import shutil
import subprocess
import time

import pytest
from PIL import Image

from core import downloader
from core.settings import Settings


@pytest.fixture(scope="module")
def srcvid(tmp_path_factory):
    d = tmp_path_factory.mktemp("conv")
    f = d / "my movie.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-c:v", "libx264", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", str(f)], check=True)
    return f


@pytest.fixture
def engine():
    e = downloader.Engine(Settings(), {
        "ytdlp": lambda: shutil.which("yt-dlp"),
        "ffdir": lambda: os.path.dirname(shutil.which("ffmpeg")),
        "deno": lambda: None,
    })
    yield e
    e.shutdown()


def wait(e, jid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in e.snapshot() if x["id"] == jid)
        if j["status"] in ("done", "error", "canceled"):
            return j
        time.sleep(0.1)
    raise AssertionError("timeout")


def probe(path, entry, stream=None):
    cmd = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + ["-show_entries", entry, "-of", "default=nw=1:nk=1", path]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.split()


def test_build_convert_args():
    a = downloader.build_convert_args("ffmpeg", "in.mkv", "o.mp4", "mp4")
    assert "libx264" in a and a[-1] == "o.mp4" and "-movflags" in a
    b = downloader.build_convert_args("ffmpeg", "in.mp4", "o.mp3", "mp3", "192", trim=(10, 5))
    assert b[b.index("-ss") + 1] == "10" and b[b.index("-t") + 1] == "5" and b.index("-ss") < b.index("-i")
    assert b[b.index("-c:a") + 1] == "libmp3lame" and b[b.index("-b:a") + 1] == "192k" and "-vn" in b
    for fmt, codec, has_br in [("m4a", "aac", True), ("opus", "libopus", True), ("flac", "flac", False), ("wav", "pcm_s16le", False)]:
        c = downloader.build_convert_args("ffmpeg", "i", "o." + fmt, fmt, "256")
        assert c[c.index("-c:a") + 1] == codec and ("-b:a" in c) == has_br


@pytest.mark.parametrize("fmt,codec", [("mp4", "h264"), ("mp3", "mp3"), ("m4a", "aac"), ("opus", "opus"), ("flac", "flac"), ("wav", "pcm_s16le")])
def test_transcode_each_format(engine, srcvid, fmt, codec):
    j = wait(engine, engine.add_transcode(str(srcvid), fmt))
    assert j["status"] == "done", j
    assert j["kind"] == "transcode" and j["title"] == "my movie"
    base = os.path.basename(j["filepath"])
    assert base.startswith("my movie") and base.endswith("." + fmt) and os.path.dirname(j["filepath"]) == str(srcvid.parent)
    assert os.path.getsize(j["filepath"]) == j["size"] > 1000
    want = "audio" if fmt != "mp4" else "video"
    assert probe(j["filepath"], "stream=codec_name", ("a:0" if want == "audio" else "v:0"))[0] == codec
    assert abs(float(probe(j["filepath"], "format=duration")[0]) - 5) < 0.8
    assert srcvid.exists()                                       # 元ファイルは消さない
    os.remove(j["filepath"])


def test_transcode_with_range(engine, srcvid):
    j = wait(engine, engine.add_transcode(str(srcvid), "mp3", section={"start": "1", "length": "2"}))
    assert j["status"] == "done", j
    assert j["filepath"].endswith("my movie [0m01s-0m03s].mp3")
    assert 1.6 < float(probe(j["filepath"], "format=duration")[0]) < 2.6
    os.remove(j["filepath"])


def test_transcode_range_clamped_to_duration(engine, srcvid):
    j = wait(engine, engine.add_transcode(str(srcvid), "m4a", section={"start": "4", "length": "10"}))  # 動画は5秒
    assert j["status"] == "done", j
    assert 0.8 < float(probe(j["filepath"], "format=duration")[0]) < 1.4   # 4〜5秒 ≒ 1秒
    os.remove(j["filepath"])


def test_transcode_fits_size_limit(engine, srcvid):
    free = wait(engine, engine.add_transcode(str(srcvid), "mp4"))
    size = free["size"]; os.remove(free["filepath"])
    limit = int(size * 0.3)
    j = wait(engine, engine.add_transcode(str(srcvid), "mp4", size_limit=limit))
    assert j["status"] == "done", j
    assert j["size"] <= limit and j["fitted"] is True
    assert not [f for f in os.listdir(srcvid.parent) if ".fit" in f]
    os.remove(j["filepath"])


def test_transcode_errors(engine, srcvid, tmp_path):
    with pytest.raises(ValueError, match="bad_file"):
        engine.add_transcode(str(tmp_path / "nope.mp4"), "mp4")
    with pytest.raises(ValueError, match="bad_format"):
        engine.add_transcode(str(srcvid), "mkv")
    junk = tmp_path / "x.mp4"; junk.write_text("not a video")
    j = wait(engine, engine.add_transcode(str(junk), "mp3"))
    assert j["status"] == "error" and j["error"] == "convert"
    assert not list(tmp_path.glob("*.mp3"))


def test_transcode_lossless_cannot_fit(engine, srcvid):
    j = wait(engine, engine.add_transcode(str(srcvid), "flac", size_limit=20_000))
    assert j["status"] == "error" and j["error"] == "size_fail"


def test_api_convert_file_and_gif_whole(srcvid):
    import main
    api = main.Api()
    api.set_setting("gif_width", "320"); api.set_setting("gif_fps", "10")
    # ファイル変換API
    assert api.convert_file(str(srcvid), "mkv") == {"ok": False, "error": "bad_format"}
    r = api.convert_file(str(srcvid), "mp3", {"start": "0", "length": "2"})
    assert r["ok"]
    j = wait(api._engine, r["id"])
    assert j["status"] == "done" and j["fmt"] == "mp3" and j["kind"] == "transcode"
    os.remove(j["filepath"])
    # GIF区間オフ（whole）→ 動画5秒ぶんのGIF
    rg = api.convert_gif(str(srcvid), {"whole": True})
    assert rg["ok"]
    jg = wait(api._engine, rg["id"])
    assert jg["status"] == "done" and jg["filepath"].endswith(".gif")
    with Image.open(jg["filepath"]) as im:
        assert im.n_frames > 20          # 10fps × 5秒 ≒ 50コマ（まるごと変換された）
    os.remove(jg["filepath"])
    api._engine.shutdown()
