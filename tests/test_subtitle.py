"""字幕機能のテスト。

このLinux環境では、本物のwhisper.cpp（Windowsバイナリ）とHugging Faceのモデル、
Google翻訳のエンドポイントに接続できないため、
  ・whisper-cli は「進捗を出してSRTを書くだけ」のスタブに差し替え
  ・翻訳は本物のGoogleの代わりにテスト用バックエンドに差し替え
て、Engineの流れ（音声抽出→文字起こし→翻訳→保存）全体を本物のffmpegで確認する。
文字起こしの精度と実翻訳APIの疎通は、ここでは確認できない（Windows実機での確認が必要）。
"""
import io
import os
import shutil
import stat
import time
import zipfile

import pytest

from core import downloader, subtitle, translate, tools
from core.settings import Settings


# ------------------------------------------------------------ 純粋ロジック
def test_srt_roundtrip():
    text = "1\n00:00:01,000 --> 00:00:02,500\nHello world\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond\n"
    cues = subtitle.parse_srt(text)
    assert cues == [{"start": 1.0, "end": 2.5, "text": "Hello world"},
                    {"start": 3.0, "end": 4.0, "text": "Second"}]
    assert subtitle.parse_srt(subtitle.build_srt(cues)) == cues


def test_time_format():
    assert subtitle.fmt_ts(3661.234) == "01:01:01,234"
    assert subtitle.fmt_ts(0) == "00:00:00,000"
    assert subtitle.parse_ts("01:01:01,234") == pytest.approx(3661.234)
    assert subtitle.parse_ts("なし") is None


def test_parse_progress():
    assert subtitle.parse_progress("whisper_print_progress_callback: progress =  42%") == 42
    assert subtitle.parse_progress("progress = 100%") == 100
    assert subtitle.parse_progress("loading model") is None


def test_srt_path_for():
    assert subtitle.srt_path_for("/a/b/動画 #1.mp4") == "/a/b/動画 #1.srt"


def test_whisper_args():
    a = subtitle.whisper_args("cli", "m.bin", "a.wav", "/out", "ja", threads=4)
    assert a[a.index("-of") + 1] == "/out" and "-osrt" in a
    assert a[a.index("-l") + 1] == "ja" and a[a.index("-t") + 1] == "4"


def test_collapse_skips_empty():
    cues = [{"start": 0, "end": 1, "text": "Hi"}, {"start": 1, "end": 2, "text": "  "},
            {"start": 2, "end": 3, "text": "Bye"}]
    texts, idx = subtitle.collapse_for_translation(cues)
    assert texts == ["Hi", "Bye"] and idx == [0, 2]


# ------------------------------------------------------------ 翻訳（まとめ訳）
def test_translate_batches_and_preserves_count():
    calls = []

    def fake(lines, target, source):
        calls.append(list(lines))
        return [f"{target}:{l}" for l in lines]

    translate.BACKENDS["fake"] = fake
    out = translate.translate_lines(["a", "b", "c", "d", "e"], "ja", "auto",
                                    backend="fake", batch_size=2)
    assert out == ["ja:a", "ja:b", "ja:c", "ja:d", "ja:e"]
    assert calls == [["a", "b"], ["c", "d"], ["e"]]          # 2件ずつまとめて送っている


def test_translate_cancel():
    translate.BACKENDS["fake2"] = lambda lines, t, s: lines
    with pytest.raises(InterruptedError):
        translate.translate_lines(["a", "b"], "ja", "auto", backend="fake2",
                                  cancel=lambda: True)


def test_google_batch_fallback_on_mismatch(monkeypatch):
    # まとめ訳で行数がズレたら1行ずつに切り替わることを確認
    def once(text, target, source):
        if "\n" in text:
            return "merged everything into one line"     # わざと1行に潰す
        return text.upper()

    monkeypatch.setattr(translate, "_google_once", once)
    out = translate._google_batch(["a", "b"], "ja", "auto")
    assert out == ["A", "B"]                              # 1行ずつにフォールバック


# ------------------------------------------------------------ whisper.cpp の展開
def test_fetch_whisper_extracts_exe_and_dll(tmp_path, monkeypatch):
    monkeypatch.setenv("OQIDA_HOME", str(tmp_path))
    monkeypatch.delenv("OQIDA_WHISPER", raising=False)
    # 本物のzip（Release/の下に exe・dll・readme が入っている）を用意
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Release/whisper-cli.exe", b"EXE")
        z.writestr("Release/ggml.dll", b"DLL")
        z.writestr("Release/readme.txt", b"ignore me")
    data = buf.getvalue()

    def fake_dl(url, dest, progress=None, cancel=None, timeout=30):
        with open(dest, "wb") as f:
            f.write(data)
        return "sha"

    monkeypatch.setattr(tools, "http_json", lambda *a, **k: (_ for _ in ()).throw(Exception("no api")))
    monkeypatch.setattr(tools, "download_file", fake_dl)
    tools._fetch_whisper(None, None)
    wdir = tools.whisper_dir()
    names = {p.name for p in wdir.iterdir()}
    assert "whisper-cli.exe" in names and "ggml.dll" in names
    assert "readme.txt" not in names                      # 実行に不要なものは取り出さない


# ------------------------------------------------------------ Engine 全体（スタブwhisper＋実ffmpeg）
WHISPER_STUB = """#!/usr/bin/env bash
out=""; prev=""
for a in "$@"; do
  if [ "$prev" = "-of" ]; then out="$a"; fi
  prev="$a"
done
echo "whisper_print_progress_callback: progress =  50%"
echo "whisper_print_progress_callback: progress = 100%"
cat > "${out}.srt" <<'SRT'
1
00:00:00,000 --> 00:00:01,500
Hello world

2
00:00:01,500 --> 00:00:03,000
This is a test
SRT
"""

EMPTY_STUB = """#!/usr/bin/env bash
out=""; prev=""
for a in "$@"; do
  if [ "$prev" = "-of" ]; then out="$a"; fi
  prev="$a"
done
: > "${out}.srt"
"""


def _write_stub(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def video(tmp_path):
    """音声つきの短い動画を作る（実ffmpeg）。"""
    import subprocess
    p = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=320x180:rate=15:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-crf", "30", "-c:a", "aac", "-shortest",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    return p


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("OQIDA_HOME", str(tmp_path / "home"))
    # whisperスタブ と ダミーモデル を用意（DLを走らせない）
    stub = tmp_path / "whisper-cli"
    _write_stub(stub, WHISPER_STUB)
    monkeypatch.setenv("OQIDA_WHISPER", str(stub))
    (tools.paths.models_dir() / "ggml-small.bin").write_bytes(b"x" * 2048)
    # 翻訳は本物のGoogleの代わりにテスト用（大文字化＋印をつける）
    translate.BACKENDS["google"] = lambda lines, t, s: [f"[{t}]{l}" for l in lines]
    e = downloader.Engine(Settings(), {
        "ytdlp": lambda: shutil.which("yt-dlp"),
        "ffdir": lambda: os.path.dirname(shutil.which("ffmpeg")),
        "deno": lambda: None,
    })
    yield e
    e.shutdown()


def _wait(e, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in e.snapshot() if x["id"] == jid)
        if j["status"] in ("done", "error", "canceled"):
            return j
        time.sleep(0.1)
    raise AssertionError("timeout")


def test_subtitle_end_to_end(engine, video):
    jid = engine.add_subtitle(str(video))
    j = _wait(engine, jid)
    assert j["status"] == "done", j
    srt = subtitle.srt_path_for(str(video))
    assert os.path.isfile(srt) and j["filepath"] == srt
    cues = subtitle.parse_srt(open(srt, encoding="utf-8").read())
    assert len(cues) == 2
    assert cues[0]["text"] == "[ja]Hello world"            # 翻訳が反映されている（既定の翻訳先=ja）
    assert j["percent"] == 100.0


def test_subtitle_no_translate(engine, video):
    engine.settings.set("sub_translate", False)
    j = _wait(engine, engine.add_subtitle(str(video)))
    assert j["status"] == "done"
    cues = subtitle.parse_srt(open(subtitle.srt_path_for(str(video)), encoding="utf-8").read())
    assert cues[0]["text"] == "Hello world"                # 翻訳オフなら元の言語のまま


def test_subtitle_no_speech(engine, video, tmp_path, monkeypatch):
    stub = tmp_path / "whisper-empty"
    _write_stub(stub, EMPTY_STUB)
    monkeypatch.setenv("OQIDA_WHISPER", str(stub))
    j = _wait(engine, engine.add_subtitle(str(video)))
    assert j["status"] == "error" and j["error"] == "no_speech"


def test_subtitle_bad_file(engine):
    with pytest.raises(ValueError):
        engine.add_subtitle("/no/such/file.mp4")
