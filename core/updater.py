"""アプリ本体の更新。GitHubのReleasesを見て、新しいインストーラーを落として静かに実行する。"""
import os
import subprocess
import sys
import threading

from . import paths
from .netutil import download_file, http_json, is_newer
from .version import UPDATE_REPO, __version__

DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


class AppUpdater:
    """state: idle / checking / uptodate / available / downloading / ready / installing / error"""

    def __init__(self, on_exit=None):
        self._lock = threading.Lock()
        self._on_exit = on_exit
        self._info = {}
        self._state = {"state": "idle", "current": __version__, "latest": "", "notes": "",
                       "done": 0, "total": 0, "error": ""}
        self._installer = None

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    # ------------------------------------------------------------ 確認
    def check(self):
        with self._lock:
            if self._state["state"] in ("checking", "downloading", "installing"):
                return
            self._state.update(state="checking", error="")
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            rel = http_json(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest")
            tag = rel.get("tag_name", "")
            asset = next((a for a in rel.get("assets", []) if a.get("name", "").lower().endswith("setup.exe")), None)
            if is_newer(tag, __version__) and asset:
                digest = (asset.get("digest") or "")
                self._info = {
                    "url": asset["browser_download_url"], "name": asset["name"],
                    "sha256": digest[7:].lower() if digest.startswith("sha256:") else "",
                }
                self._set(state="available", latest=tag.lstrip("vV"),
                          notes=(rel.get("body") or "")[:800], total=int(asset.get("size") or 0), done=0)
            else:
                self._set(state="uptodate", latest=tag.lstrip("vV") or __version__)
        except Exception as e:  # noqa: BLE001
            self._set(state="error", error=_short(e))

    # ------------------------------------------------------------ ダウンロード→適用
    def download(self):
        with self._lock:
            if self._state["state"] != "available":
                return
            self._state.update(state="downloading", done=0, error="")
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        try:
            dest = paths.tmp_dir() / self._info["name"]
            got = download_file(self._info["url"], dest, lambda d, t: self._set(done=d, total=t or self._state["total"]))
            want = self._info.get("sha256")
            if want and got.lower() != want:
                dest.unlink(missing_ok=True)
                raise RuntimeError("checksum mismatch")
            self._installer = str(dest)
            self._set(state="ready")
        except Exception as e:  # noqa: BLE001
            self._set(state="error", error=_short(e))

    def apply(self):
        """ダウンロード済みのインストーラーを起動して、アプリ自身は終了する。"""
        with self._lock:
            if self._state["state"] != "ready" or not self._installer:
                return False
            if not getattr(sys, "frozen", False) and not os.environ.get("OQIDA_FORCE_INSTALL"):
                self._state.update(state="error", error="dev_mode")
                return False
            self._state["state"] = "installing"
            exe = self._installer
        try:
            subprocess.Popen([exe, "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART", "/SP-"],
                             creationflags=DETACHED if paths.IS_WINDOWS else 0, close_fds=True)
        except Exception as e:  # noqa: BLE001
            self._set(state="error", error=_short(e))
            return False
        if self._on_exit:
            threading.Timer(0.8, self._on_exit).start()
        return True


def _short(e):
    s = str(e) or e.__class__.__name__
    return s[:200]


class YtdlpUpdater:
    """yt-dlp本体の更新。ダウンロード中は入れ替えないで、終わるまで待つ。"""

    def __init__(self, is_busy, get_skip=lambda: "", on_installed=lambda: None):
        self._is_busy = is_busy
        self._get_skip = get_skip          # 巻き戻したときに「この版は入れない」と覚えておく値
        self._on_installed = on_installed
        self._lock = threading.Lock()
        self._state = {"state": "idle", "current": "", "latest": "", "error": ""}

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    def check(self, auto_apply=False):
        with self._lock:
            if self._state["state"] in ("checking", "updating", "waiting"):
                return
            self._state.update(state="checking", error="")
        threading.Thread(target=self._check, args=(auto_apply,), daemon=True).start()

    def _check(self, auto_apply):
        from . import tools
        try:
            r = tools.check_ytdlp_update()
            self._set(current=r["current"] or "", latest=r["latest"])
            skip = (self._get_skip() or "").strip()
            if r["available"] and skip and r["latest"].lstrip("vV") == skip:
                self._set(state="skipped")                    # 巻き戻した版と同じ。自動では入れない（手動なら入れられる）
            elif r["available"]:
                self._set(state="available")
                if auto_apply:
                    self._apply()
            else:
                self._set(state="uptodate")
        except Exception as e:  # noqa: BLE001
            self._set(state="error", error=_short(e))

    def update(self):
        with self._lock:
            if self._state["state"] in ("updating", "waiting", "checking"):
                return
        threading.Thread(target=self._apply, daemon=True).start()

    def _apply(self):
        from . import tools
        try:
            if self._is_busy():
                self._set(state="waiting")
                while self._is_busy():
                    import time
                    time.sleep(1)
            self._set(state="updating")
            tools.update_ytdlp()
            self._on_installed()
            self._set(state="updated", current=tools.ytdlp_version() or "")
        except Exception as e:  # noqa: BLE001
            self._set(state="error", error=_short(e))
