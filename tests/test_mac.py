"""macOS対応まわりのテスト（このLinux環境では実行時の.appは作れないので、
URLの選び方・アーキ判定・引数の分岐など、プラットフォーム依存のロジックだけ確認する）。"""
import os

import pytest

from core import downloader, paths, tools


# ------------------------------------------------------------ アーキ判定
def test_mac_arch(monkeypatch):
    import platform
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert tools._mac_arch() == "arm64" and tools._deno_arch() == "aarch64"
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert tools._mac_arch() == "x64" and tools._deno_arch() == "x86_64"


# ------------------------------------------------------------ 保存場所
def test_mac_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("OQIDA_HOME", raising=False)
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    d = paths.data_dir()
    assert d == tmp_path / "Library" / "Application Support" / "OQIDA"


# ------------------------------------------------------------ build_args の分岐
def test_build_args_windows_filenames_only_on_windows(monkeypatch):
    job = {"fmt": "mp4", "quality": "best", "bitrate": "320", "url": "https://x/y",
           "section": None, "save_thumb": False, "size_limit": 0}
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    assert "--windows-filenames" in downloader.build_args(job, "/out", "yt", "/ff", None)
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    a = downloader.build_args(job, "/out", "yt", "/ff", None)
    assert "--windows-filenames" not in a
    assert a[a.index("--encoding") + 1] == "utf-8"        # 文字化け対策は両方で有効


# ------------------------------------------------------------ 取得URLの選び方（実際には落とさない）
def test_fetch_ytdlp_uses_macos_asset(monkeypatch):
    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.setattr(tools, "http_json", lambda *a, **k: (_ for _ in ()).throw(Exception("no api")))
    captured = {}
    monkeypatch.setattr(tools, "download_file",
                        lambda url, dest, *a, **k: captured.update(url=url) or "sha")
    monkeypatch.setattr(tools, "_install_ytdlp", lambda tmp: None)
    tools._fetch_ytdlp(None, None)
    assert captured["url"].endswith("/yt-dlp_macos")


def test_fetch_ffmpeg_mac_picks_arch_binaries(monkeypatch):
    monkeypatch.setattr(tools, "_mac_arch", lambda: "arm64")
    monkeypatch.setattr(tools, "http_json", lambda *a, **k: (_ for _ in ()).throw(Exception("no api")))
    got = []
    monkeypatch.setattr(tools, "_download_bin",
                        lambda url, name, progress, cancel: got.append((name, url)))
    tools._fetch_ffmpeg_mac(None, None)
    names = dict(got)
    assert names["ffmpeg"].endswith("/ffmpeg-darwin-arm64")
    assert names["ffprobe"].endswith("/ffprobe-darwin-arm64")
    assert tools.FFMPEG_MAC_FALLBACK_TAG in names["ffmpeg"]


def test_fetch_deno_mac_url(monkeypatch):
    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.setattr(tools, "_deno_arch", lambda: "aarch64")
    captured = {}
    monkeypatch.setattr(tools, "_fetch_zip_members",
                        lambda url, wanted, p, c: captured.update(url=url, wanted=wanted))
    monkeypatch.setattr(tools, "_fetch_ytdlp", lambda p, c: None)
    tools.fetch("deno", None, None)
    assert captured["url"].endswith("/deno-aarch64-apple-darwin.zip")
    assert captured["wanted"] == {"deno"}


def test_fetch_allowed_on_mac(monkeypatch):
    # macOSでは OQIDA_ALLOW_FETCH なしでも取得が許可される（例外にならない）
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.delenv("OQIDA_ALLOW_FETCH", raising=False)
    monkeypatch.setattr(tools, "_fetch_ytdlp", lambda p, c: None)
    tools.fetch("ytdlp", None, None)                      # 例外が出なければOK


def test_subtitle_disabled_on_mac(monkeypatch):
    from core.settings import Settings
    monkeypatch.setattr(paths, "IS_MAC", True)
    e = downloader.Engine(Settings())
    try:
        e.settings.set("auto_subtitle", True)
        assert e._subtitle_wanted() is False             # Macでは自動字幕は走らない
    finally:
        e.shutdown()
