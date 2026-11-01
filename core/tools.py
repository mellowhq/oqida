"""yt-dlp / ffmpeg / deno の取得と更新。

アプリ本体には同梱せず、初回起動時に GitHub から取得して %LOCALAPPDATA%\\OQIDA\\bin に置く。
こうしておくと、YouTube側の仕様変更でyt-dlpが壊れても、アプリを作り直さずに更新できる。
"""
import json
import os
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

from . import paths
from .netutil import download_file, http_json, is_newer

YTDLP_REPO = "yt-dlp/yt-dlp"
YTDLP_URL = f"https://github.com/{YTDLP_REPO}/releases/latest/download/yt-dlp.exe"
# macOS版の yt-dlp はユニバーサルバイナリ（Apple Silicon・Intel 両対応の1本）
YTDLP_MAC_URL = f"https://github.com/{YTDLP_REPO}/releases/latest/download/yt-dlp_macos"
FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"

# macOSの ffmpeg / ffprobe は、GitHubで配布している静的バイナリ(descriptinc)から取得する。
# 資産名は ffmpeg-darwin-arm64 / ffmpeg-darwin-x64 のように {名前}-darwin-{アーキ}。
FFMPEG_MAC_REPO = "descriptinc/ffmpeg-ffprobe-static"
FFMPEG_MAC_FALLBACK_TAG = "b6.1.2-rc.1"      # APIが使えないとき用の控え（上記資産が揃っている既知のタグ）


def _mac_arch():
    """descriptinc の資産名に使うアーキ名（arm64 / x64）。"""
    import platform
    return "arm64" if platform.machine() == "arm64" else "x64"


def _deno_arch():
    """deno の資産名に使うアーキ名（aarch64 / x86_64）。"""
    import platform
    return "aarch64" if platform.machine() == "arm64" else "x86_64"

# 字幕の文字起こしに使う whisper.cpp（本体に同梱せず、字幕を初めて使うときに bin/whisper へ取得する）
WHISPER_REPO = "ggml-org/whisper.cpp"
WHISPER_ASSET = "whisper-bin-x64.zip"           # Windows・CPU版。中に whisper-cli.exe と必要なDLLが入っている
# whisper.cpp は「v1.9.x（ソースのみ）」と「bNNNN（Windowsバイナリ付き）」の2系統でリリースしており、
# releases/latest はソースのみを指すことがある。そのため、バイナリが付いたリリースを一覧から探す。
# 下は、APIが使えないとき用の控え（whisper-bin-x64.zip が付いていた既知のリリース）。
WHISPER_FALLBACK_TAG = "b5454"
# 音声認識モデル。Hugging Face から取得する。大きさ(MB)はダウンロード前の目安表示に使う
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"
WHISPER_MODELS = {"tiny": 75, "base": 142, "small": 466, "medium": 1500, "large-v3": 2900}

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


def whisper_dir():
    """whisper.cpp 一式（本体＋DLL）の置き場所。"""
    p = paths.bin_dir() / "whisper"
    p.mkdir(parents=True, exist_ok=True)
    return p


def whisper_cli_path():
    """字幕の文字起こしに使う whisper-cli の場所。無ければ None。"""
    env = os.environ.get("OQIDA_WHISPER")
    if env:
        return env
    p = whisper_dir() / _exe("whisper-cli")
    if p.exists():
        return str(p)
    # Windows以外（開発・テスト用）はPATHから探す
    return None if paths.IS_WINDOWS else shutil.which("whisper-cli")


def whisper_model_path(name):
    return paths.models_dir() / f"ggml-{name}.bin"


def has_whisper():
    return whisper_cli_path() is not None


def has_model(name):
    return whisper_model_path(name).exists()


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


def ytdlp_bin_path():
    """アプリが管理するyt-dlpの置き場所（binフォルダ）"""
    return paths.bin_dir() / _exe("yt-dlp")


def _ytdlp_prev_path():
    return paths.bin_dir() / _exe("yt-dlp.previous")


def _ytdlp_prev_info():
    return paths.bin_dir() / "yt-dlp.previous.json"


def exe_version(path):
    """実行ファイルの --version の結果。動かなければ None"""
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=30,
                             creationflags=NO_WINDOW)
        v = out.stdout.strip()
        return v if out.returncode == 0 and v else None
    except Exception:
        return None


def previous_ytdlp_version():
    """巻き戻し先の版。なければ None"""
    try:
        if not _ytdlp_prev_path().exists():
            return None
        return json.loads(_ytdlp_prev_info().read_text(encoding="utf-8")).get("version") or "?"
    except Exception:
        return "?" if _ytdlp_prev_path().exists() else None


def _install_ytdlp(new_file):
    """新しいyt-dlpを入れる。先に動くことを確かめ、今の版は「前の版」として残す。"""
    new_file = Path(new_file)
    if not paths.IS_WINDOWS:
        os.chmod(new_file, 0o755)
    newv = exe_version(new_file)
    if not newv:
        try:
            os.remove(new_file)
        except OSError:
            pass
        raise RuntimeError("the downloaded yt-dlp does not run")
    cur = ytdlp_bin_path()
    if cur.exists():
        oldv = exe_version(cur)
        shutil.copy2(cur, _ytdlp_prev_path())
        _ytdlp_prev_info().write_text(json.dumps({"version": oldv or "?"}), encoding="utf-8")
    _replace(new_file, cur)


def rollback_ytdlp():
    """今のyt-dlpと「前の版」を入れ替える（もう一度呼ぶと元に戻る）。返り値: (今の版, 入れ替え前の版)"""
    cur, prev = ytdlp_bin_path(), _ytdlp_prev_path()
    if not prev.exists():
        raise RuntimeError("no previous version")
    curv = exe_version(cur) if cur.exists() else None
    swap = paths.bin_dir() / _exe("yt-dlp.swap")
    if cur.exists():
        _replace(cur, swap)
    _replace(prev, cur)
    if swap.exists():
        _replace(swap, prev)
        _ytdlp_prev_info().write_text(json.dumps({"version": curv or "?"}), encoding="utf-8")
    return exe_version(cur), curv


def _fetch_ytdlp(progress, cancel):
    """最新のyt-dlpを取得。GitHubがsha256を教えてくれる場合は照合する（Windowsのみ照合）。"""
    asset = "yt-dlp_macos" if paths.IS_MAC else "yt-dlp.exe"
    url = YTDLP_MAC_URL if paths.IS_MAC else YTDLP_URL
    want_sha = None
    try:
        rel = http_json(f"https://api.github.com/repos/{YTDLP_REPO}/releases/latest")
        for a in rel.get("assets", []):
            if a.get("name") == asset:
                url = a["browser_download_url"]
                d = a.get("digest") or ""
                if d.startswith("sha256:"):
                    want_sha = d[7:].lower()
    except Exception:
        pass
    tmp = paths.tmp_dir() / _exe("yt-dlp.new")
    got = download_file(url, tmp, progress, cancel)
    if want_sha and got.lower() != want_sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("yt-dlp checksum mismatch")
    _install_ytdlp(tmp)


def _download_bin(url, name, progress, cancel):
    """1本のバイナリをダウンロードして bin/ に置き、実行できるようにする（macOSの ffmpeg 等）。"""
    tmp = paths.bin_dir() / (name + ".new")
    download_file(url, tmp, progress, cancel)
    if not paths.IS_WINDOWS:
        os.chmod(tmp, 0o755)
    _replace(tmp, paths.bin_dir() / name)


def _fetch_ffmpeg_mac(progress, cancel):
    """macOS用の ffmpeg と ffprobe を descriptinc から取得して bin/ に置く。"""
    arch = _mac_arch()
    names = {"ffmpeg": f"ffmpeg-darwin-{arch}", "ffprobe": f"ffprobe-darwin-{arch}"}
    base = f"https://github.com/{FFMPEG_MAC_REPO}/releases/download/{FFMPEG_MAC_FALLBACK_TAG}"
    urls = {local: f"{base}/{asset}" for local, asset in names.items()}
    try:                                                     # バイナリが揃っている最新リリースをAPIから探す
        rels = http_json(f"https://api.github.com/repos/{FFMPEG_MAC_REPO}/releases?per_page=20")
        for rel in rels:
            have = {a.get("name"): a.get("browser_download_url") for a in rel.get("assets", [])}
            if all(names[l] in have for l in names):
                urls = {l: have[names[l]] for l in names}
                break
    except Exception:
        pass
    # 2本まとめて進捗を出す（0〜50% / 50〜100%）
    _download_bin(urls["ffmpeg"], "ffmpeg", lambda d, t: progress and progress(d, t * 2 if t else 0), cancel)
    _download_bin(urls["ffprobe"], "ffprobe",
                  lambda d, t: progress and progress((t or 0) + d, t * 2 if t else 0), cancel)


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
                    if not paths.IS_WINDOWS:               # macOS等では実行権限を付ける
                        os.chmod(dst, 0o755)
                    _replace(dst, paths.bin_dir() / base)
                    found.add(base)
    finally:
        tmp.unlink(missing_ok=True)
    if found != set(wanted):
        raise RuntimeError(f"missing in zip: {set(wanted) - found}")


def _whisper_asset_url():
    """whisper-bin-x64.zip（Windows・CPU版）が付いている最新リリースのダウンロードURLを返す。
    'latest' はソースのみのことがあるので、リリース一覧からバイナリ付きのものを探す。"""
    try:
        rels = http_json(f"https://api.github.com/repos/{WHISPER_REPO}/releases?per_page=30")
        for rel in rels:                                     # 一覧は新しい順。バイナリが付いた最初のものを使う
            for a in rel.get("assets", []):
                if a.get("name") == WHISPER_ASSET:
                    return a["browser_download_url"]
    except Exception:
        pass
    # APIが使えないときは、バイナリが付いていた既知のリリースから取る
    return f"https://github.com/{WHISPER_REPO}/releases/download/{WHISPER_FALLBACK_TAG}/{WHISPER_ASSET}"


def _fetch_whisper(progress, cancel):
    """whisper.cpp（CPU版）をGitHubから取得して bin/whisper に展開する。
    zipの中は Release/ の下に whisper-cli.exe と複数のDLLが入っているので、
    フォルダ構成は無視して実行ファイルとDLLを whisper フォルダへ平らに取り出す。"""
    url = _whisper_asset_url()
    tmp = paths.tmp_dir() / "whisper.zip.part"
    download_file(url, tmp, progress, cancel)
    wdir = whisper_dir()
    got_cli = False
    try:
        with zipfile.ZipFile(tmp) as z:
            for m in z.namelist():
                if m.endswith("/"):
                    continue
                base = os.path.basename(m)
                if not base.lower().endswith((".exe", ".dll")):
                    continue                                 # 実行ファイルとDLLだけでよい（README等は不要）
                dst = wdir / (base + ".new")
                with z.open(m) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
                _replace(dst, wdir / base)
                if base.lower() == "whisper-cli.exe":
                    got_cli = True
    finally:
        tmp.unlink(missing_ok=True)
    if not got_cli:
        raise RuntimeError("whisper-cli.exe was not found in the archive")


def fetch_model(name, progress=None, cancel=None):
    """音声認識モデルを Hugging Face から取得する。"""
    if name not in WHISPER_MODELS:
        raise ValueError(f"unknown model: {name}")
    dst = whisper_model_path(name)
    tmp = paths.tmp_dir() / f"ggml-{name}.bin.part"
    download_file(MODEL_URL.format(name), tmp, progress, cancel)
    _replace(tmp, dst)


def fetch(component, progress=None, cancel=None):
    if not (paths.IS_WINDOWS or paths.IS_MAC) and not os.environ.get("OQIDA_ALLOW_FETCH"):
        raise RuntimeError("tool download is supported on Windows and macOS")
    if component == "ytdlp":
        _fetch_ytdlp(progress, cancel)
    elif component == "ffmpeg":
        if paths.IS_MAC:
            _fetch_ffmpeg_mac(progress, cancel)
        else:
            _fetch_zip_members(FFMPEG_URL, {"ffmpeg.exe", "ffprobe.exe"}, progress, cancel)
    elif component == "deno":
        if paths.IS_MAC:
            _fetch_zip_members(f"https://github.com/denoland/deno/releases/latest/download/"
                               f"deno-{_deno_arch()}-apple-darwin.zip", {"deno"}, progress, cancel)
        else:
            _fetch_zip_members(DENO_URL, {"deno.exe"}, progress, cancel)
    elif component == "whisper":
        _fetch_whisper(progress, cancel)
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
