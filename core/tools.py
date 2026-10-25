"""yt-dlp / ffmpeg / deno の取得と更新。

アプリ本体には同梱せず、初回起動時に GitHub から取得して %LOCALAPPDATA%\\OQIDA\\bin に置く。
こうしておくと、YouTube側の仕様変更でyt-dlpが壊れても、アプリを作り直さずに更新できる。
"""
import os
import shutil
import subprocess
import threading
import zipfile

from . import paths
from .netutil import download_file, http_json, is_newer

YTDLP_REPO = "yt-dlp/yt-dlp"
YTDLP_URL = f"https://github.com/{YTDLP_REPO}/releases/latest/download/yt-dlp.exe"
FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"

NO_WINDOW = 0x08000000 if paths.IS_WINDOWS else 0


def _exe(name: str) -> str:
    return name + (".exe" if paths.IS_WINDOWS else "")


def ytdlp_path():
    env = os.environ.get("OQIDA_YTDLP")
    if env:
        return env
    p = paths.bin_dir() / _exe("yt-dlp")
    if p.exists():
        return str(p)
    # Windows以外（開発・テスト用）はPATHから探す
    return None if paths.IS_WINDOWS else shutil.which("yt-dlp")


def ffmpeg_dir():
    env = os.environ.get("OQIDA_FFMPEG_DIR")
    if env:
        return env
    b = paths.bin_dir()
    if (b / _exe("ffmpeg")).exists():
        return str(b)
    if not paths.IS_WINDOWS:
        w = shutil.which("ffmpeg")
        return str(os.path.dirname(w)) if w else None
    return None


def ffmpeg_exe(ffdir):
    """ffmpegの実行ファイルのパス"""
    return os.path.join(ffdir, _exe("ffmpeg"))


def ffprobe_exe(ffdir):
    p = os.path.join(ffdir, _exe("ffprobe"))
    if not os.path.exists(p) and not paths.IS_WINDOWS:     # 開発用: ffmpegと別の場所にある場合はPATHから探す
        return shutil.which("ffprobe") or p
    return p


def deno_path():
    p = paths.bin_dir() / _exe("deno")
    if p.exists():
        return str(p)
    return None if paths.IS_WINDOWS else shutil.which("deno")


def ytdlp_version():
    exe = ytdlp_path()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW)
        v = out.stdout.strip()
        return v or None
    except Exception:
        return None


_ver_cache = {"path": None, "mtime": None, "ver": None, "busy": False}


def ytdlp_version_cached():
    """画面の更新のたびに呼ばれるので、子プロセスの起動は裏で1回だけ行い、結果を使い回す。
    まだ調べ終わっていない間はNoneを返す（画面側は空表示）。"""
    exe = ytdlp_path()
    if not exe:
        return None
    try:
        mt = os.path.getmtime(exe)
    except OSError:
        return None
    c = _ver_cache
    if c["path"] == exe and c["mtime"] == mt:
        return c["ver"]
    if not c["busy"]:
        c["busy"] = True

        def work():
            v = ytdlp_version()
            c.update(path=exe, mtime=mt, ver=v, busy=False)

        threading.Thread(target=work, daemon=True).start()
    return c["ver"] if c["path"] == exe else None


def status():
    return {
        "ytdlp": ytdlp_path() is not None,
        "ffmpeg": ffmpeg_dir() is not None,
        "deno": deno_path() is not None,
    }


def missing():
    s = status()
    return [k for k in ("ytdlp", "ffmpeg", "deno") if not s[k]]


# ---------------------------------------------------------------- 取得

def _replace(src, dst):
    os.replace(src, dst)


def _fetch_ytdlp(progress, cancel):
    """最新のyt-dlp.exeを取得。GitHubがsha256を教えてくれる場合は照合する。"""
    url, want_sha = YTDLP_URL, None
    try:
        rel = http_json(f"https://api.github.com/repos/{YTDLP_REPO}/releases/latest")
        for a in rel.get("assets", []):
            if a.get("name") == "yt-dlp.exe":
                url = a["browser_download_url"]
                d = a.get("digest") or ""
                if d.startswith("sha256:"):
                    want_sha = d[7:].lower()
    except Exception:
        pass
    tmp = paths.tmp_dir() / "yt-dlp.exe.part"
    got = download_file(url, tmp, progress, cancel)
    if want_sha and got.lower() != want_sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("yt-dlp checksum mismatch")
    _replace(tmp, paths.bin_dir() / "yt-dlp.exe")


def _fetch_zip_members(url, wanted, progress, cancel):
    """zipを取得して、wantedに含まれるファイル名(basename)だけをbinに取り出す。"""
    tmp = paths.tmp_dir() / "download.zip.part"
    download_file(url, tmp, progress, cancel)
    found = set()
    try:
        with zipfile.ZipFile(tmp) as z:
            for m in z.namelist():
                base = os.path.basename(m)
                if base in wanted and not m.endswith("/"):
                    dst = paths.bin_dir() / (base + ".new")
                    with z.open(m) as src, open(dst, "wb") as out:
                        shutil.copyfileobj(src, out)
                    _replace(dst, paths.bin_dir() / base)
                    found.add(base)
    finally:
        tmp.unlink(missing_ok=True)
    if found != set(wanted):
        raise RuntimeError(f"missing in zip: {set(wanted) - found}")


def fetch(component, progress=None, cancel=None):
    if not paths.IS_WINDOWS and not os.environ.get("OQIDA_ALLOW_FETCH"):
        raise RuntimeError("tool download is Windows-only")
    if component == "ytdlp":
        _fetch_ytdlp(progress, cancel)
    elif component == "ffmpeg":
        _fetch_zip_members(FFMPEG_URL, {"ffmpeg.exe", "ffprobe.exe"}, progress, cancel)
    elif component == "deno":
        _fetch_zip_members(DENO_URL, {"deno.exe"}, progress, cancel)
    else:
        raise ValueError(component)


class Bootstrap:
    """足りない部品をまとめて取得する。UIはsnapshot()を定期的に見る。"""

    ORDER = ("ytdlp", "deno", "ffmpeg")

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._state = {"running": False, "component": "", "done": 0, "total": 0, "error": ""}

    def snapshot(self):
        with self._lock:
            return dict(self._state, missing=missing())

    def start(self, components=None):
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._state = {"running": True, "component": "", "done": 0, "total": 0, "error": ""}
        threading.Thread(target=self._run, args=(components,), daemon=True).start()
        return True

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    def _run(self, components):
        try:
            todo = components or [c for c in self.ORDER if c in missing()]
            for c in todo:
                self._set(component=c, done=0, total=0)
                fetch(c, progress=lambda d, t: self._set(done=d, total=t))
        except Exception as e:  # noqa: BLE001
            self._set(error=str(e) or e.__class__.__name__)
        finally:
            with self._lock:
                self._running = False
                self._state["running"] = False
                self._state["component"] = ""


# ---------------------------------------------------------------- yt-dlp更新

def check_ytdlp_update():
    """{'current':..., 'latest':..., 'available': bool}。ネットに繋がらなければ例外。"""
    cur = ytdlp_version()
    rel = http_json(f"https://api.github.com/repos/{YTDLP_REPO}/releases/latest")
    latest = rel.get("tag_name", "")
    return {"current": cur, "latest": latest, "available": bool(cur) and is_newer(latest, cur)}


def update_ytdlp(progress=None):
    """yt-dlp.exeを最新に入れ替える。ダウンロード実行中は呼ばないこと。"""
    if os.environ.get("OQIDA_YTDLP"):
        raise RuntimeError("yt-dlp is overridden by OQIDA_YTDLP")
    _fetch_ytdlp(progress, None)
