"""保存場所まわり。Windowsでは %LOCALAPPDATA%\\OQIDA を使う。"""
import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def data_dir() -> Path:
    override = os.environ.get("OQIDA_HOME")
    if override:
        base = Path(override)
    elif IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OQIDA"
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support" / "OQIDA"
    else:
        base = Path.home() / ".oqida"
    base.mkdir(parents=True, exist_ok=True)
    return base


def bin_dir() -> Path:
    p = data_dir() / "bin"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tmp_dir() -> Path:
    p = data_dir() / "tmp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    """字幕用の音声認識モデル（Whisper）の置き場所。サイズが大きいので本体とは分けて保存する。"""
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path:
    return data_dir() / "settings.json"


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / "OQIDA"


def resource_dir() -> Path:
    """uiフォルダなど同梱ファイルの場所（PyInstaller対応）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent
