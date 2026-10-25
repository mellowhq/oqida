import json
import locale
import re
import threading

from . import paths

DEFAULTS = {
    "theme": "dark",            # dark / light / system
    "accent": "#ff8a3d",        # アクセントカラー（#rrggbb）
    "language": "auto",         # auto / ja / en
    "download_dir": "",         # 空ならデフォルト
    "format": "mp4",            # mp4 / mp3 / m4a / opus / flac / wav / gif
    "mp4_quality": "best",      # best / 1080 / 720 / 480
    "mp3_bitrate": "320",       # 320 / 192 / 128
    "gif_width": "480",         # 320 / 480 / 640
    "gif_fps": "15",            # 10 / 15 / 20
    "conv_format": "mp4",       # ファイル変換の出力形式
    "max_parallel": "1",        # 同時ダウンロード数 1〜4
    "speed_limit": "0",         # 0=無制限 / 0.5 / 1 / 2 / 5 / 10 (MB/秒)
    "save_thumb": False,        # サムネイル画像も保存する
    "history_keep": True,       # 履歴を残す
    "ytdlp_skip": "",           # 巻き戻したときに、見送るyt-dlpの版
    "size_limit_mb": "0",       # 0=上限なし / 8 / 10 / 25 / 50 / 100 / 500 / 1000
    "cookies_browser": "none",  # none / edge / chrome / firefox
    "auto_check_app": True,
    "auto_update_ytdlp": True,
}

CHOICES = {
    "theme": {"dark", "light", "system"},
    "language": {"auto", "ja", "en"},
    "format": {"mp4", "mp3", "m4a", "opus", "flac", "wav", "gif"},
    "max_parallel": {"1", "2", "3", "4"},
    "speed_limit": {"0", "0.5", "1", "2", "5", "10"},
    "mp4_quality": {"best", "2160", "1440", "1080", "720", "480", "360", "240", "144"},
    "mp3_bitrate": {"320", "192", "128"},
    "gif_width": {"320", "480", "640"},
    "gif_fps": {"10", "15", "20"},
    "conv_format": {"mp4", "mp3", "m4a", "opus", "flac", "wav"},
    "size_limit_mb": {"0", "8", "10", "25", "50", "100", "500", "1000"},
    "cookies_browser": {"none", "edge", "chrome", "firefox"},
}


def system_language() -> str:
    try:
        lang = (locale.getlocale()[0] or "") or (locale.getdefaultlocale()[0] or "")
    except Exception:
        lang = ""
    return "ja" if lang.lower().startswith("ja") else "en"


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self):
        f = paths.settings_file()
        if f.exists():
            try:
                saved = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    for k, v in saved.items():
                        if k in DEFAULTS and self._valid(k, v):
                            self._data[k] = v
            except Exception:
                pass  # 壊れていたらデフォルトで起動する

    @staticmethod
    def _valid(key, value):
        if key in CHOICES:
            return value in CHOICES[key]
        if key in ("auto_check_app", "auto_update_ytdlp", "save_thumb", "history_keep"):
            return isinstance(value, bool)
        if key == "download_dir":
            return isinstance(value, str)
        if key == "ytdlp_skip":
            return isinstance(value, str) and re.fullmatch(r"[0-9A-Za-z.+_\-]{0,40}", value) is not None
        if key == "accent":
            return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None
        return False

    def get(self, key):
        with self._lock:
            return self._data[key]

    def all(self):
        with self._lock:
            d = dict(self._data)
        d["download_dir_effective"] = self.download_dir()
        d["language_effective"] = system_language() if d["language"] == "auto" else d["language"]
        return d

    def set(self, key, value):
        if key not in DEFAULTS or not self._valid(key, value):
            raise ValueError(f"invalid setting: {key}={value!r}")
        with self._lock:
            self._data[key] = value
            self._save_locked()

    def _save_locked(self):
        f = paths.settings_file()
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)

    def download_dir(self) -> str:
        d = self.get("download_dir")
        return d if d else str(paths.default_download_dir())
