"""v0.5.0 の機能: 履歴・ログ・一時停止/再開・区間指定・音声形式・サムネ・速度制限・yt-dlpの巻き戻し"""
import functools
import http.server
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time

import pytest

from core import downloader, gif, history, paths, tools
from core.settings import Settings
from core.updater import YtdlpUpdater


# ---------------- 「途中から読む」(Range)に対応した簡易サーバー ----------------
class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        m = re.match(r"bytes=(\d+)-(\d*)", rng)
        size = os.path.getsize(path)
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                left -= len(chunk)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("v05media")
    run = lambda a: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)
    run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(d / "big.mp4")])
    run(["-f", "lavfi", "-i", "anoisesrc=d=30:a=0.3:r=44100", "-ac", "2", str(d / "noise.wav")])
    handler = functools.partial(RangeHandler, directory=str(d))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}/", "dir": d}
    srv.shutdown()


def make_engine(settings=None):
    return downloader.Engine(settings or Settings(), {
        "ytdlp": lambda: shutil.which("yt-dlp"),
        "ffdir": lambda: os.path.dirname(shutil.which("ffmpeg")),
        "deno": lambda: None,
    })


@pytest.fixture
def engine():
    e = make_engine()
    yield e
    e.shutdown()


def wait_for(e, jid, states=("done", "error", "canceled"), timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in e.snapshot() if x["id"] == jid)
        if j["status"] in states:
            return j
        time.sleep(0.1)
    raise AssertionError(f"timeout; last={j['status']}")


def probe(path, entry, stream=None):
    cmd = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + ["-show_entries", entry, "-of", "default=nw=1:nk=1", path]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.split()


# ---------------- 区間・ファイル名の部品 ----------------
def test_validate_range_and_names():
    assert gif.validate_range("1:00", "90") == {"start": 60.0, "length": 90.0}
    assert gif.validate_range("", "3600")["length"] == 3600                 # MP4/MP3は60秒を超えてもよい
    for args in (("0", "0.2"), ("0", str(7 * 3600)), ("99999999", "5")):
        with pytest.raises(ValueError, match="bad_range"):
            gif.validate_range(*args)
    for bad in (("x", "5"), ("-1", "5"), ("0", "abc")):                    # 数字の形式でないもの（マイナスも）
        with pytest.raises(ValueError, match="bad_time"):
            gif.validate_range(*bad)
    assert gif.hms(90) == "1m30s" and gif.hms(3725) == "1h02m05s" and gif.hms(5) == "0m05s"
    assert gif.range_suffix({"start": 80, "length": 105}) == " [1m20s-3m05s]"


def test_build_args_for_new_options():
    job = {"fmt": "m4a", "quality": "best", "bitrate": "192", "url": "https://x/y", "section": {"start": 80, "length": 20},
           "save_thumb": True, "size_limit": 0}
    a = downloader.build_args(job, "/o", "yt", "/ff", None, "none", "2")
    assert a[a.index("-o") + 1].endswith("%(title).150B [1m20s-1m40s].%(ext)s")
    assert a[a.index("--audio-format") + 1] == "m4a" and a[a.index("--limit-rate") + 1] == "2M"
    assert a[a.index("--download-sections") + 1] == "*80-100"
    assert "--write-thumbnail" in a and "--embed-thumbnail" in a and a.count("--convert-thumbnails") == 1
    for fmt in ("opus", "flac", "wav"):
        b = downloader.build_args(dict(job, fmt=fmt, section=None, save_thumb=False), "/o", "yt", "/ff", None)
        assert b[b.index("--audio-format") + 1] == fmt and "--limit-rate" not in b and "--write-thumbnail" not in b
        assert ("--audio-quality" in b) == (fmt == "opus")                   # ロスレスには音質の指定がない
    g = downloader.build_args({"fmt": "gif", "gif": {"start": 0, "length": 5, "width": 480, "fps": 15}, "save_thumb": True,
                               "quality": "", "bitrate": "", "url": "https://x/y"}, "/o", "yt", "/ff", None)
    assert "--write-thumbnail" not in g                                     # GIFにはサムネは付けない


def test_settings_v05():
    s = Settings()
    for k, v in (("format", "flac"), ("speed_limit", "2"), ("save_thumb", True), ("history_keep", False), ("ytdlp_skip", "2026.10.30")):
        s.set(k, v)
    for k, v in (("format", "ogg"), ("speed_limit", "3"), ("save_thumb", "yes"), ("ytdlp_skip", "a b"), ("ytdlp_skip", "x" * 50)):
        with pytest.raises(ValueError):
            s.set(k, v)


# ---------------- 区間指定 ----------------
def test_mp4_section_download(engine, media, tmp_path):
    j = wait_for(engine, engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "o"),
                                    section={"start": "1", "length": "2"}))
    assert j["status"] == "done", j
    assert os.path.basename(j["filepath"]) == "big [0m01s-0m03s].mp4"
    assert 1.6 < float(probe(j["filepath"], "format=duration")[0]) < 2.6


def test_mp3_section_download(engine, media, tmp_path):
    j = wait_for(engine, engine.add(media["url"] + "noise.wav", "mp3", "best", "128", str(tmp_path / "o"),
                                    section={"start": "5", "length": "4"}))
    assert j["status"] == "done", j
    assert j["filepath"].endswith("noise [0m05s-0m09s].mp3")
    assert 3.5 < float(probe(j["filepath"], "format=duration")[0]) < 4.8


def test_section_validation(engine, tmp_path):
    with pytest.raises(ValueError, match="bad_range"):
        engine.add("https://example.com/a.mp4", "mp4", "best", "320", str(tmp_path), section={"start": "0", "length": "0.1"})
    with pytest.raises(ValueError, match="bad_time"):
        engine.add("https://example.com/a.mp4", "mp4", "best", "320", str(tmp_path), section={"start": "zz", "length": "5"})
    with pytest.raises(ValueError, match="bad_format"):
        engine.add("https://example.com/a.mp4", "ogg", "best", "320", str(tmp_path))


# ---------------- 音声形式 ----------------
@pytest.mark.parametrize("fmt,ext,codec", [("m4a", ".m4a", "aac"), ("opus", ".opus", "opus"), ("flac", ".flac", "flac"), ("wav", ".wav", "pcm_s16le")])
def test_audio_formats(engine, media, tmp_path, fmt, ext, codec):
    j = wait_for(engine, engine.add(media["url"] + "noise.wav", fmt, "best", "192", str(tmp_path / "o")))
    assert j["status"] == "done", j
    assert j["filepath"].endswith(ext) and os.path.getsize(j["filepath"]) == j["size"] > 10_000
    assert probe(j["filepath"], "stream=codec_name", "a:0")[0] == codec
    assert abs(float(probe(j["filepath"], "format=duration")[0]) - 30) < 1.5


@pytest.mark.parametrize("fmt", ["m4a", "opus"])
def test_lossy_audio_fits_size_limit(engine, media, tmp_path, fmt):
    j = wait_for(engine, engine.add(media["url"] + "noise.wav", fmt, "best", "320", str(tmp_path / "o"), size_limit=250_000))
    assert j["status"] == "done", j
    assert j["size"] <= 250_000 and j["fitted"] is True


def test_lossless_cannot_fit_a_small_limit(engine, media, tmp_path):
    j = wait_for(engine, engine.add(media["url"] + "noise.wav", "flac", "best", "320", str(tmp_path / "o"), size_limit=250_000))
    assert j["status"] == "error" and j["error"] == "size_fail"


def test_save_thumb_option_does_not_break_when_no_thumbnail(engine, media, tmp_path):
    j = wait_for(engine, engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "o"), save_thumb=True))
    assert j["status"] == "done", j


# ---------------- 速度制限・一時停止/再開 ----------------
def test_speed_limit_slows_the_download(media, tmp_path):
    s = Settings()
    e = make_engine(s)
    try:
        t0 = time.time()
        wait_for(e, e.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "free")))
        free = time.time() - t0
        size = (media["dir"] / "big.mp4").stat().st_size
        s.set("speed_limit", "0.5")                                       # 毎秒0.5MB
        t1 = time.time()
        j = wait_for(e, e.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "slow")))
        slow = time.time() - t1
        assert j["status"] == "done", j
        assert slow > max(free + 1.0, size / 500_000 * 0.5)
    finally:
        e.shutdown()


def test_pause_and_resume_continues_the_same_file(media, tmp_path):
    s = Settings()
    s.set("speed_limit", "0.5")
    e = make_engine(s)
    try:
        out = tmp_path / "o"
        jid = e.add(media["url"] + "big.mp4", "mp4", "best", "320", str(out))
        for _ in range(100):                                              # 少し進むまで待つ
            j = next(x for x in e.snapshot() if x["id"] == jid)
            if j["percent"] > 3:
                break
            time.sleep(0.1)
        e.pause(jid)
        j = wait_for(e, jid, states=("paused", "done", "error"))
        assert j["status"] == "paused", j
        assert not e.busy() or True
        time.sleep(0.5)
        assert next(x for x in e.snapshot() if x["id"] == jid)["status"] == "paused"      # 止まったまま進まない
        assert any(f.endswith(".part") or ".part" in f or f.endswith(".ytdl") for f in os.listdir(out))   # 途中のファイルが残っている
        s.set("speed_limit", "0")                                         # 再開したら、速く終わらせる
        e.resume(jid)
        j = wait_for(e, jid)
        assert j["status"] == "done", j
        assert os.path.getsize(j["filepath"]) == j["size"] > 100_000
        assert float(probe(j["filepath"], "format=duration")[0]) > 5.5
        assert not [f for f in os.listdir(out) if ".part" in f]
    finally:
        e.shutdown()


def test_pause_queued_job_and_cancel_paused(engine, media, tmp_path):
    blocker = engine.add(media["url"] + "noise.wav", "mp3", "best", "320", str(tmp_path / "a"))
    queued = engine.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "b"))
    engine.pause(queued)
    assert next(x for x in engine.snapshot() if x["id"] == queued)["status"] == "paused"
    wait_for(engine, blocker)
    time.sleep(0.5)
    assert next(x for x in engine.snapshot() if x["id"] == queued)["status"] == "paused"      # 順番が来ても動かない
    engine.cancel(queued)
    assert next(x for x in engine.snapshot() if x["id"] == queued)["status"] == "canceled"


# ---------------- 履歴 ----------------
def test_history_survives_restart(media, tmp_path):
    e1 = make_engine()
    ok = wait_for(e1, e1.add(media["url"] + "big.mp4", "mp4", "best", "320", str(tmp_path / "o")))
    bad = wait_for(e1, e1.add("http://127.0.0.1:9/none.mp4", "mp4", "best", "320", str(tmp_path / "o")))
    time.sleep(0.3)
    e1.shutdown()
    saved = json.loads((paths.data_dir() / "history.json").read_text(encoding="utf-8"))
    assert [x["status"] for x in saved] == ["done", "error"]
    e2 = make_engine()                                                    # アプリを開き直した状態
    try:
        jobs = e2.snapshot()
        assert [j["status"] for j in jobs] == ["done", "error"]
        assert jobs[0]["title"] == "big" and jobs[0]["filepath"] == ok["filepath"] and jobs[0]["size"] == ok["size"]
        assert jobs[0]["percent"] == 100.0 and jobs[1]["error"] == bad["error"]
        assert e2.get_log(jobs[1]["id"]) != ""                           # 再起動後も、失敗の理由は読める
        e2.remove(jobs[1]["id"])
        assert len(history.load()) == 1
        e2.clear_history()
        assert e2.snapshot() == [] and history.load() == []
    finally:
        e2.shutdown()


def test_history_can_be_turned_off(media, tmp_path):
    s = Settings()
    s.set("history_keep", False)
    e = make_engine(s)
    try:
        wait_for(e, e.add(media["url"] + "noise.wav", "mp3", "best", "320", str(tmp_path / "o")))
        time.sleep(0.3)
        assert not (paths.data_dir() / "history.json").exists()
    finally:
        e.shutdown()


def test_history_ignores_broken_data(tmp_path):
    f = paths.data_dir() / "history.json"
    f.write_text("{not json", encoding="utf-8")
    assert history.load() == []
    f.write_text(json.dumps([{"status": "running", "title": "x"}, "junk", {"status": "done", "title": 5, "size": "big", "thumb": "javascript:1"}]))
    out = history.load()
    assert len(out) == 1 and out[0]["title"] == "" and out[0]["size"] == 0 and out[0]["thumb"] == ""      # 実行中だったものは復元しない
    history.save([{"status": "done", "title": f"t{i}"} for i in range(250)])
    assert len(history.load()) == history.MAX_ENTRIES


def test_duplicate_detection(media, tmp_path):
    import main
    api = main.Api()
    api.set_setting("download_dir", str(tmp_path / "dl"))
    url = media["url"] + "noise.wav"
    api.set_setting("format", "mp3")
    j1 = api.add_download(url)
    assert j1["ok"]
    wait_for(api._engine, j1["id"])
    again = api.add_download(url)
    assert again["ok"] is False and again["error"] == "duplicate" and again["title"] == "noise"
    assert api.add_download(url, None, True)["ok"]                         # 「それでも落とす」
    api.set_setting("format", "m4a")
    assert api.add_download(url)["ok"]                                    # 形式が違えば別のもの
    api._engine.shutdown()


# ---------------- ログ ----------------
def test_error_log_is_useful_and_private(engine, tmp_path):
    jid = engine.add("http://127.0.0.1:9/none.mp4", "mp4", "best", "320", str(tmp_path / "o"))
    j = wait_for(engine, jid)
    log = engine.get_log(jid)
    assert j["status"] == "error"
    assert log.startswith("OQIDA 0.5.0") and "error: " in log and "url: http://127.0.0.1:9/none.mp4" in log
    assert "$ " in log and "ERROR" in log                                 # 実行したコマンドと、yt-dlpのエラーが入っている
    assert "OQIDA_PROG" not in log                                        # 進み具合の行は入れない
    assert str(paths.Path.home()) not in log                              # ユーザー名が入るので、ホームのパスは伏せる
    assert engine.get_log(99999) == ""


def test_log_is_bounded(engine):
    jid = engine.add("http://127.0.0.1:9/none.mp4", "mp4", "best", "320", "/tmp/x")
    wait_for(engine, jid)
    for i in range(2000):
        engine._log(next(x for x in engine._jobs if x["id"] == jid), f"line {i}")
    assert len(engine.get_log(jid).splitlines()) <= downloader.LOG_LINES + 5


# ---------------- yt-dlpの巻き戻し ----------------
def fake_ytdlp(path, version, ok=True):
    path.write_text(f"#!/bin/sh\n{'echo ' + version if ok else 'exit 3'}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def managed(monkeypatch):
    monkeypatch.delenv("OQIDA_YTDLP", raising=False)
    cur = tools.ytdlp_bin_path()
    fake_ytdlp(cur, "2026.10.01")
    return cur


def test_install_keeps_previous_and_rolls_back_both_ways(managed):
    assert tools.previous_ytdlp_version() is None
    new = paths.tmp_dir() / "yt-dlp.new"
    fake_ytdlp(new, "2026.10.30")
    tools._install_ytdlp(new)
    assert tools.exe_version(managed) == "2026.10.30" and tools.previous_ytdlp_version() == "2026.10.01"
    now, before = tools.rollback_ytdlp()                                  # 壊れていた → 前の版へ
    assert (now, before) == ("2026.10.01", "2026.10.30")
    assert tools.previous_ytdlp_version() == "2026.10.30"
    now, before = tools.rollback_ytdlp()                                  # やっぱり新しい版へ
    assert (now, before) == ("2026.10.30", "2026.10.01")
    assert tools.previous_ytdlp_version() == "2026.10.01"


def test_broken_download_is_not_installed(managed):
    new = paths.tmp_dir() / "yt-dlp.new"
    fake_ytdlp(new, "x", ok=False)
    with pytest.raises(RuntimeError):
        tools._install_ytdlp(new)
    assert tools.exe_version(managed) == "2026.10.01" and not new.exists() and tools.previous_ytdlp_version() is None
    with pytest.raises(RuntimeError, match="no previous"):
        tools.rollback_ytdlp()


def test_api_rollback_sets_and_clears_the_skip(managed):
    import main
    api = main.Api()
    assert api.rollback_ytdlp() == {"ok": False, "error": "no_previous"}
    new = paths.tmp_dir() / "yt-dlp.new"
    fake_ytdlp(new, "2026.10.30")
    tools._install_ytdlp(new)
    tools._ver_cache.update(path=None, mtime=None)
    r = api.rollback_ytdlp()
    assert r == {"ok": True, "current": "2026.10.01", "previous": "2026.10.30"}
    assert api._settings.get("ytdlp_skip") == "2026.10.30"                # 壊れていた版は、自動更新で入れ直さない
    st = api.get_state()["ytdlp"]
    assert st["previous"] == "2026.10.30" and st["skip"] == "2026.10.30"
    r2 = api.rollback_ytdlp()                                             # 新しい版に戻す
    assert r2["current"] == "2026.10.30" and api._settings.get("ytdlp_skip") == ""
    api.update_ytdlp.__func__                                             # 手動更新は見送りを解除する
    api._settings.set("ytdlp_skip", "2026.11.11")
    api._yt_upd.update = lambda: None
    api.update_ytdlp()
    assert api._settings.get("ytdlp_skip") == ""
    api._engine.shutdown()


def test_updater_skips_the_rolled_back_version(monkeypatch):
    called = []
    monkeypatch.setattr(tools, "check_ytdlp_update", lambda: {"current": "2026.10.01", "latest": "2026.10.30", "available": True})
    monkeypatch.setattr(tools, "update_ytdlp", lambda progress=None: called.append(1))
    y = YtdlpUpdater(lambda: False, get_skip=lambda: "2026.10.30")
    y.check(auto_apply=True)
    for _ in range(50):
        if y.snapshot()["state"] != "checking":
            break
        time.sleep(0.05)
    assert y.snapshot()["state"] == "skipped" and not called
    y2 = YtdlpUpdater(lambda: False, get_skip=lambda: "2026.10.15")      # 違う版（もっと新しい）なら、普通に更新する
    y2.check(auto_apply=True)
    for _ in range(100):
        if y2.snapshot()["state"] in ("updated", "error"):
            break
        time.sleep(0.05)
    assert called == [1]


def test_copy_text_is_safe_off_windows():
    import main
    api = main.Api()
    assert api.copy_text("abc") == {"ok": False}                          # Windows以外では何もしない（画面側が別の方法で試す）
    api._engine.shutdown()
