import functools
import http.server
import os
import shutil
import subprocess
import threading
import time

import pytest
from PIL import Image

from core import downloader, gif, paths, sizefit
from core.settings import Settings


# ---------------- 計算（純粋な関数） ----------------
def test_limit_bytes():
    assert sizefit.limit_bytes("10") == 10_000_000
    assert sizefit.limit_bytes(8) == 8_000_000
    for v in ("0", "", None, "abc", -5, "-1"):
        assert sizefit.limit_bytes(v) == 0


def test_mp3_bitrate_for():
    # 10分・5MB → 約62kbpsまで使える → 梯子の中で収まる一番高い 56
    assert sizefit.mp3_bitrate_for(600, 5_000_000, 320) == 56
    assert sizefit.mp3_bitrate_for(600, 500_000_000, 320) == 320           # 余裕があれば希望の音質のまま
    assert sizefit.mp3_bitrate_for(600, 500_000_000, 128) == 128           # 希望より上げない
    assert sizefit.mp3_bitrate_for(3600, 1_000_000, 320) is None            # 1時間を1MBには収められない
    assert sizefit.mp3_bitrate_for(0, 1_000_000, 320) is None


def test_mp3_choice_really_fits():
    for dur in (30, 200, 1800):
        for limit in (500_000, 3_000_000, 10_000_000):
            b = sizefit.mp3_bitrate_for(dur, limit, 320)
            if b:
                assert b * 1000 / 8 * dur <= limit * sizefit.SAFETY + 1


def test_video_plan():
    p = sizefit.video_plan(60, 10_000_000)            # 1分を10MB → 約1.2Mbps
    assert p and 1000 <= p["v_kbps"] + p["a_kbps"] <= 1300 and p["height"] == 480
    assert (p["v_kbps"] + p["a_kbps"]) * 1000 / 8 * 60 <= 10_000_000
    assert sizefit.video_plan(60, 500_000_000)["height"] == 1080
    assert sizefit.video_plan(3600, 1_000_000) is None
    assert sizefit.video_plan(60, 10_000_000, src_height=240)["height"] == 240   # 元より大きくしない
    r = sizefit.retry_video_plan(p, 12_000_000, 10_000_000)
    assert r["v_kbps"] < p["v_kbps"]


def test_next_gif_params():
    cur = {"width": 640, "fps": 20, "colors": 256}
    n1 = sizefit.next_gif_params(cur, 640, 40_000_000, 10_000_000, 1)
    assert n1["width"] < 640 and n1["colors"] == 256 and n1["fps"] == 20
    n2 = sizefit.next_gif_params(n1, n1["width"], 20_000_000, 10_000_000, 2)
    assert n2["colors"] == 128 and n2["fps"] <= 12
    n4 = sizefit.next_gif_params(n2, n2["width"], 20_000_000, 10_000_000, 4)
    assert n4["fps"] <= 8 and n4["colors"] <= 64
    assert sizefit.next_gif_params(cur, 80, 99_000_000, 10_000_000, 1) is None           # もう縮められない
    assert sizefit.next_gif_params(cur, 640, 99_000_000, 10_000_000, sizefit.MAX_GIF_ATTEMPTS) is None
    ws = []
    c = cur
    for att in range(1, 5):
        c = sizefit.next_gif_params(c, c["width"], 30_000_000, 10_000_000, att)
        ws.append(c["width"])
    assert ws == sorted(ws, reverse=True) and ws[-1] >= sizefit.MIN_GIF_WIDTH         # だんだん小さくなる
    assert sizefit.next_gif_params(c, c["width"], 30_000_000, 10_000_000, 5) is None   # 最小幅まで縮んだら、そこで諦める


def test_gif_dimensions(tmp_path):
    p = tmp_path / "a.gif"
    Image.new("RGB", (123, 45), (200, 30, 30)).save(p)
    assert gif.gif_dimensions(str(p)) == (123, 45)
    (tmp_path / "x.gif").write_bytes(b"nope")
    assert gif.gif_dimensions(str(tmp_path / "x.gif")) is None
    assert gif.gif_dimensions(str(tmp_path / "missing.gif")) is None


def test_settings_size_limit():
    s = Settings()
    s.set("size_limit_mb", "10")
    assert Settings().get("size_limit_mb") == "10"
    for bad in ("11", "-1", "ten", 10):
        with pytest.raises(ValueError):
            s.set("size_limit_mb", bad)


# ---------------- 実際に作って確かめる ----------------
@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("sizemedia")
    run = lambda a: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)
    # 6秒・640x360。高画質で作るので、そのままだと数MBになる
    run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", str(d / "big.mp4")])    # 簡易サーバーは「途中から読む」に対応しないので、目次を先頭に置く
    # 30秒のノイズ音声（圧縮しにくいので大きくなる）
    run(["-f", "lavfi", "-i", "anoisesrc=d=30:a=0.3:r=44100", "-ac", "2", str(d / "noise.wav")])
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}/", "dir": d}
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


def wait_done(e, jid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in e.snapshot() if x["id"] == jid)
        if j["status"] in ("done", "error", "canceled"):
            return j
        time.sleep(0.2)
    raise AssertionError("timeout")


def probe(path, entry):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entry, "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True).stdout.split()
    return [float(x) for x in out]


def test_mp4_is_shrunk_to_fit(engine, media, tmp_path):
    free = engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "free"))
    jf = wait_done(engine, free)
    assert jf["status"] == "done" and jf["size"] > 1_000_000 and jf["fitted"] is False
    limit = int(jf["size"] * 0.25)
    jid = engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "fit"), size_limit=limit)
    j = wait_done(engine, jid)
    assert j["status"] == "done", j
    assert j["fitted"] is True and os.path.getsize(j["filepath"]) == j["size"] <= limit
    assert j["size"] > limit * 0.3                                     # 小さくしすぎない（目標の近くに収まる）
    assert abs(probe(j["filepath"], "format=duration")[0] - 6) < 0.6    # 長さは変わらない
    assert os.listdir(tmp_path / "fit") == [os.path.basename(j["filepath"])]       # 作業用ファイルが残らない


def test_mp4_already_small_is_untouched(engine, media, tmp_path):
    jid = engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "o"), size_limit=500_000_000)
    j = wait_done(engine, jid)
    assert j["status"] == "done" and j["fitted"] is False


def test_mp3_bitrate_is_chosen_to_fit(engine, media, tmp_path):
    free = wait_done(engine, engine.add(media["url"] + "noise.wav", "mp3", "best", "320", str(tmp_path / "free")))
    assert free["status"] == "done" and free["size"] > 1_000_000        # 30秒・320kbpsは約1.2MB
    limit = 300_000
    j = wait_done(engine, engine.add(media["url"] + "noise.wav", "mp3", "best", "320", str(tmp_path / "fit"), size_limit=limit))
    assert j["status"] == "done", j
    assert j["fitted"] is True and j["size"] <= limit and j["size"] > 100_000
    assert abs(probe(j["filepath"], "format=duration")[0] - 30) < 1.0


def test_impossible_limit_fails_clearly(engine, media, tmp_path):
    j = wait_done(engine, engine.add(media["url"] + "noise.wav", "mp3", "best", "320", str(tmp_path / "o"), size_limit=20_000))
    assert j["status"] == "error" and j["error"] == "size_fail"
    j2 = wait_done(engine, engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "o2"), size_limit=15_000))
    assert j2["status"] == "error" and j2["error"] == "size_fail"


def test_gif_is_remade_until_it_fits(engine, media, tmp_path):
    src = media["dir"] / "big.mp4"
    gif_in = {"start": "0", "length": "4", "width": 640, "fps": 20}
    free = wait_done(engine, engine.add_local(str(src), gif_in))
    assert free["status"] == "done" and free["size"] > 1_000_000
    free_w = gif.gif_dimensions(free["filepath"])[0]
    os.remove(free["filepath"])
    limit = int(free["size"] * 0.2)
    j = wait_done(engine, engine.add_local(str(src), gif_in, size_limit=limit))
    assert j["status"] == "done", j
    assert j["size"] <= limit and j["fitted"] is True
    assert gif.gif_dimensions(j["filepath"])[0] < free_w                # 幅を下げて収めた
    with Image.open(j["filepath"]) as im:
        assert im.format == "GIF" and im.n_frames > 5
    assert sum(1 for f in os.listdir(media["dir"]) if f.endswith(".gif")) == 1    # 試行ごとにファイルが増えない
    os.remove(j["filepath"])


def test_gif_that_fits_first_time_is_not_marked_fitted(engine, media, tmp_path):
    src = media["dir"] / "big.mp4"
    j = wait_done(engine, engine.add_local(str(src), {"start": "0", "length": "1", "width": 320, "fps": 10}, size_limit=50_000_000))
    assert j["status"] == "done" and j["fitted"] is False
    os.remove(j["filepath"])


def test_gif_impossible_limit_leaves_no_file(engine, media):
    src = media["dir"] / "big.mp4"
    before = set(os.listdir(media["dir"]))
    j = wait_done(engine, engine.add_local(str(src), {"start": "0", "length": "4", "width": 640, "fps": 20}, size_limit=1_500))
    assert j["status"] == "error" and j["error"] == "size_fail"
    assert set(os.listdir(media["dir"])) == before


def test_downloaded_gif_also_respects_limit(engine, media, tmp_path):
    out = tmp_path / "o"
    limit = 400_000
    j = wait_done(engine, engine.add(media["url"] + "big.mp4", "gif", "best", "320", str(out),
                                     gif={"start": "0", "length": "3", "width": 640, "fps": 20}, size_limit=limit))
    assert j["status"] == "done", j
    assert j["size"] <= limit and os.listdir(out) == [os.path.basename(j["filepath"])]
    assert not [d for d in os.listdir(paths.tmp_dir()) if d.startswith("gif")]


def test_cancel_during_fit_leaves_nothing(engine, media, tmp_path):
    out = tmp_path / "o"
    jid = engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(out), size_limit=300_000)
    for _ in range(300):
        j = next(x for x in engine.snapshot() if x["id"] == jid)
        if j["stage"] == "convert" or j["status"] != "running" and j["status"] != "queued":
            break
        time.sleep(0.02)
    engine.cancel(jid)
    j = wait_done(engine, jid)
    assert j["status"] in ("canceled", "done")                         # 速すぎて先に終わる場合もある
    assert not [f for f in os.listdir(out) if ".fit" in f] if out.exists() else True


def test_api_passes_limit_and_clamps_range(media, tmp_path):
    import main
    api = main.Api()
    api.set_setting("download_dir", str(tmp_path / "dl"))
    api.set_setting("size_limit_mb", "10")
    api.set_setting("gif_width", "320"); api.set_setting("gif_fps", "10")
    src = str(media["dir"] / "big.mp4")                                 # 長さ6秒
    assert api.convert_gif(src, {"start": "9", "length": "3"}) == {"ok": False, "error": "bad_range"}
    assert api.convert_gif(src, {"start": "6", "length": "3"}) == {"ok": False, "error": "bad_range"}
    r = api.convert_gif(src, {"start": "4", "length": "10"})            # 4〜14秒 → 動画の終わり(6秒)で切り詰め
    assert r["ok"]
    j = None
    for _ in range(200):
        j = next(x for x in api.get_state()["jobs"] if x["id"] == r["id"])
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert j["status"] == "done", j
    assert j["size_limit"] == 10_000_000 and j["gif"]["length"] == pytest.approx(6 - 4, abs=0.1)
    os.remove(j["filepath"])
    api._engine.shutdown()
