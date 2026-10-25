import os
import shutil
import time

import pytest
from PIL import Image

from core import downloader, gif, paths
from core.settings import Settings


def test_parse_time():
    assert gif.parse_time("") == 0 and gif.parse_time(None) == 0
    assert gif.parse_time("90") == 90
    assert gif.parse_time("1:30") == 90
    assert gif.parse_time("01:02:03") == 3723
    assert gif.parse_time("1:30.5") == 90.5
    assert gif.parse_time(" 2：05 ") == 125          # 全角コロンも可
    for bad in ("abc", "1:2:3:4", "-5", "1:-3", "1,5", "1::2"):
        with pytest.raises(ValueError, match="bad_time"):
            gif.parse_time(bad)


def test_validate():
    g = gif.validate("1:00", "10", "480", "15")
    assert g == {"start": 60.0, "length": 10.0, "width": 480, "fps": 15}
    assert gif.validate("", "0.5", 320, 10)["start"] == 0
    for args in (("0", "0.4", 480, 15), ("0", "61", 480, 15), ("0", "10", 500, 15), ("0", "10", 480, 30), ("0", "x", 480, 15)):
        with pytest.raises(ValueError):
            gif.validate(*args)
    with pytest.raises(ValueError, match="bad_time"):
        gif.validate("1:xx", "10", 480, 15)


def test_section_and_ffmpeg_args():
    g = {"start": 12.5, "length": 7.5, "width": 480, "fps": 15}
    assert gif.section_arg(g) == "*12.5-20"
    a = gif.build_ffmpeg_args("ffmpeg", "in.mp4", "out.gif", 15, 480)
    assert a[0] == "ffmpeg" and a[-1] == "out.gif" and "-an" in a
    vf = a[a.index("-vf") + 1]
    assert "fps=15" in vf and "min(480,iw)" in vf and "palettegen" in vf and "paletteuse" in vf


def test_progress_seconds_and_unique_path(tmp_path):
    assert gif.progress_seconds("out_time_us=1500000") == 1.5
    assert gif.progress_seconds("out_time_ms=2500000") == 2.5
    assert gif.progress_seconds("frame=3") is None and gif.progress_seconds("out_time_us=N/A") is None
    (tmp_path / "a.gif").write_bytes(b"x")
    assert gif.unique_path(str(tmp_path), "a", ".gif").endswith("a (1).gif")
    (tmp_path / "a (1).gif").write_bytes(b"x")
    assert gif.unique_path(str(tmp_path), "a", ".gif").endswith("a (2).gif")


@pytest.fixture
def engine():
    e = downloader.Engine(Settings(), {
        "ytdlp": lambda: shutil.which("yt-dlp"),
        "ffdir": lambda: os.path.dirname(shutil.which("ffmpeg")),
        "deno": lambda: None,
    })
    yield e
    e.shutdown()


def wait_done(e, jid, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in e.snapshot() if x["id"] == jid)
        if j["status"] in ("done", "error", "canceled"):
            return j
        time.sleep(0.2)
    raise AssertionError("timeout")


def test_gif_job_creates_trimmed_gif(engine, media_server, tmp_path):
    out = tmp_path / "out"
    jid = engine.add(media_server, "gif", "best", "320", str(out),
                     gif={"start": "0.5", "length": "1.5", "width": 320, "fps": 10})
    j = wait_done(engine, jid)
    assert j["status"] == "done", j
    assert j["filepath"].endswith(".gif") and os.path.dirname(j["filepath"]) == str(out)
    assert j["percent"] == 100.0 and j["stage"] == "" and j["title"] == "sample"
    with Image.open(j["filepath"]) as im:
        assert im.format == "GIF"
        assert im.size[0] <= 320
        assert 9 <= im.n_frames <= 20          # 10fps × 1.5秒 ≒ 15コマ
        assert im.info.get("loop") == 0         # くり返し再生
    assert os.listdir(out) == [os.path.basename(j["filepath"])]          # 途中の動画は残らない
    assert not [d for d in os.listdir(paths.tmp_dir()) if d.startswith("gif")]


def test_gif_job_never_overwrites(engine, media_server, tmp_path):
    out = tmp_path / "out"
    names = []
    for _ in range(2):
        jid = engine.add(media_server, "gif", "best", "320", str(out), gif={"start": "0", "length": "1", "width": 320, "fps": 10})
        j = wait_done(engine, jid)
        assert j["status"] == "done", j
        names.append(os.path.basename(j["filepath"]))
    assert sorted(names) == ["sample (1).gif", "sample.gif"]


@pytest.fixture
def local_video(tmp_path):
    import subprocess
    d = tmp_path / "videos"; d.mkdir()
    f = d / "my clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f)], check=True)
    return f


def test_probe_duration(local_video, tmp_path):
    d = gif.probe_duration(shutil.which("ffprobe"), str(local_video))
    assert d is not None and 3.9 < d < 4.2
    bad = tmp_path / "not_video.txt"; bad.write_text("hello")
    assert gif.probe_duration(shutil.which("ffprobe"), str(bad)) is None
    assert gif.probe_duration("/no/such/ffprobe", str(local_video)) is None


def test_trim_args():
    a = gif.build_ffmpeg_args("ffmpeg", "in.mp4", "o.gif", 10, 320, trim=(12.5, 3))
    assert a[a.index("-ss") + 1] == "12.5" and a[a.index("-t") + 1] == "3"
    assert a.index("-ss") < a.index("-i")               # 先に位置を指定する方が速い
    assert "-ss" not in gif.build_ffmpeg_args("ffmpeg", "in.mp4", "o.gif", 10, 320)


def test_local_convert_makes_gif_next_to_source(engine, local_video):
    jid = engine.add_local(str(local_video), {"start": "1", "length": "2", "width": 320, "fps": 10})
    j = wait_done(engine, jid)
    assert j["status"] == "done", j
    assert j["kind"] == "convert" and j["title"] == "my clip"
    assert j["filepath"] == str(local_video.with_suffix(".gif"))
    with Image.open(j["filepath"]) as im:
        assert im.size[0] == 320 and 15 <= im.n_frames <= 24      # 10fps × 2秒 ≒ 20コマ
    assert local_video.exists()                                     # 元の動画は消さない
    jid2 = engine.add_local(str(local_video), {"start": "0", "length": "1", "width": 320, "fps": 10})
    assert wait_done(engine, jid2)["filepath"].endswith("my clip (1).gif")   # 上書きしない


def test_local_convert_errors(engine, tmp_path):
    with pytest.raises(ValueError, match="bad_file"):
        engine.add_local(str(tmp_path / "nope.mp4"), {"start": "0", "length": "5", "width": 480, "fps": 15})
    junk = tmp_path / "junk.mp4"; junk.write_text("this is not a video")
    with pytest.raises(ValueError, match="bad_gif"):
        engine.add_local(str(junk), {"start": "0", "length": "500", "width": 480, "fps": 15})
    jid = engine.add_local(str(junk), {"start": "0", "length": "5", "width": 480, "fps": 15})
    j = wait_done(engine, jid)
    assert j["status"] == "error" and j["error"] == "convert"
    assert not list(tmp_path.glob("*.gif"))                         # 失敗したときに空のGIFを残さない


def test_api_inspect_and_convert(local_video, tmp_path):
    import main
    api = main.Api()
    info = api.inspect_video(str(local_video))
    assert info["ok"] and info["name"] == "my clip.mp4" and 3.9 < info["duration"] < 4.2
    assert api.inspect_video(str(tmp_path / "missing.mp4")) == {"ok": False, "error": "bad_file"}
    api.set_setting("gif_width", "320"); api.set_setting("gif_fps", "10")
    assert api.convert_gif(str(local_video), {"start": "x", "length": "3"}) == {"ok": False, "error": "bad_time"}
    assert api.convert_gif(str(tmp_path / "missing.mp4"), {"start": "0", "length": "3"}) == {"ok": False, "error": "bad_file"}
    r = api.convert_gif(str(local_video), {"start": "0", "length": "2"})
    assert r["ok"]
    for _ in range(150):
        j = api.get_state()["jobs"][0]
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert j["status"] == "done" and j["kind"] == "convert", j
    api._engine.shutdown()


def test_gif_validation_errors(engine, tmp_path):
    with pytest.raises(ValueError, match="bad_gif"):
        engine.add("https://example.com/a.mp4", "gif", "best", "320", str(tmp_path))
    with pytest.raises(ValueError, match="bad_time"):
        engine.add("https://example.com/a.mp4", "gif", "best", "320", str(tmp_path), gif={"start": "zz", "length": "5", "width": 480, "fps": 15})
    with pytest.raises(ValueError, match="bad_gif"):
        engine.add("https://example.com/a.mp4", "gif", "best", "320", str(tmp_path), gif={"start": "0", "length": "120", "width": 480, "fps": 15})


def test_api_gif_flow(media_server, tmp_path):
    import main
    api = main.Api()
    api.set_setting("download_dir", str(tmp_path / "dl"))
    api.set_setting("format", "gif")
    api.set_setting("gif_width", "320")
    api.set_setting("gif_fps", "10")
    assert api.add_download(media_server, {"start": "abc", "length": "5"}) == {"ok": False, "error": "bad_time"}
    assert api.add_download(media_server, {"start": "0", "length": "999"}) == {"ok": False, "error": "bad_gif"}
    r = api.add_download(media_server, {"start": "0", "length": "1"})
    assert r["ok"]
    for _ in range(150):
        j = api.get_state()["jobs"][0]
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert j["status"] == "done", j
    assert j["fmt"] == "gif" and j["filepath"].endswith(".gif")
    api._engine.shutdown()
