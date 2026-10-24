"""OQIDA - YouTubeのURLからMP4/MP3を保存する個人用ソフト。"""
import json
import os
import subprocess
import sys
import threading

from core import downloader, paths, tools
from core.settings import Settings
from core.updater import AppUpdater, YtdlpUpdater
from core.version import APP_NAME, __version__

NO_WINDOW = 0x08000000 if paths.IS_WINDOWS else 0


class Api:
    """画面(JavaScript)から呼ばれる窓口。先頭が _ のものは画面から見えない。"""

    def __init__(self):
        self._settings = Settings()
        self._engine = downloader.Engine(self._settings)
        self._boot = tools.Bootstrap()
        self._app_upd = AppUpdater(on_exit=self._quit)
        self._yt_upd = YtdlpUpdater(self._engine.busy)
        self._window = None
        self._started = False

    # ------------------------------------------------------------ 状態
    def get_state(self):
        return {
            "version": __version__,
            "settings": self._settings.all(),
            "jobs": self._engine.snapshot(),
            "setup": self._boot.snapshot(),
            "app_update": self._app_upd.snapshot(),
            "ytdlp": dict(self._yt_upd.snapshot(), current=tools.ytdlp_version_cached()),
        }

    def startup(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._startup_flow, daemon=True).start()

    def _startup_flow(self):
        fresh = False
        if tools.missing():
            fresh = True
            self._boot.start()
            while self._boot.snapshot()["running"]:
                threading.Event().wait(0.3)
        if self._settings.get("auto_update_ytdlp") and not fresh and not tools.missing():
            self._yt_upd.check(auto_apply=True)
        if self._settings.get("auto_check_app"):
            self._app_upd.check()

    def retry_setup(self):
        self._boot.start()

    def reinstall_tool(self, name):
        if name in ("ytdlp", "ffmpeg", "deno") and not self._engine.busy():
            self._boot.start([name])

    # ------------------------------------------------------------ 設定
    def set_setting(self, key, value):
        try:
            self._settings.set(key, value)
            return {"ok": True}
        except ValueError:
            return {"ok": False}

    def pick_folder(self):
        import webview
        cur = self._settings.download_dir()
        os.makedirs(cur, exist_ok=True)
        fd = getattr(webview, "FileDialog", None)   # 新しいpywebviewはFileDialog.FOLDER、古いものはFOLDER_DIALOG
        kind = fd.FOLDER if fd is not None else webview.FOLDER_DIALOG
        res = self._window.create_file_dialog(kind, directory=cur)
        if res:
            self._settings.set("download_dir", res[0] if isinstance(res, (list, tuple)) else res)
        return {"ok": bool(res)}

    def open_download_dir(self):
        d = self._settings.download_dir()
        os.makedirs(d, exist_ok=True)
        _open_path(d)

    def open_data_dir(self):
        _open_path(str(paths.data_dir()))

    def reveal(self, job_id):
        for j in self._engine.snapshot():
            if j["id"] == job_id and j["filepath"] and os.path.exists(j["filepath"]):
                _reveal(j["filepath"])
                return
        self.open_download_dir()

    def paste_clipboard(self):
        return _read_clipboard()

    # ------------------------------------------------------------ ダウンロード
    def add_download(self, url):
        s = self._settings
        try:
            jid = self._engine.add(url, s.get("format"), s.get("mp4_quality"), s.get("mp3_bitrate"),
                                   s.download_dir())
            return {"ok": True, "id": jid}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def cancel(self, job_id):
        self._engine.cancel(job_id)

    def remove(self, job_id):
        self._engine.remove(job_id)

    def retry(self, job_id):
        self._engine.retry(job_id)

    def clear_finished(self):
        self._engine.clear_finished()

    # ------------------------------------------------------------ 更新
    def check_app_update(self):
        self._app_upd.check()

    def download_app_update(self):
        self._app_upd.download()

    def apply_app_update(self):
        if self._engine.busy():
            return {"ok": False, "error": "busy"}
        return {"ok": bool(self._app_upd.apply())}

    def check_ytdlp(self):
        self._yt_upd.check()

    def update_ytdlp(self):
        self._yt_upd.update()

    # ------------------------------------------------------------ 終了
    def _quit(self):
        self._engine.shutdown()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
        os._exit(0)


def _open_path(p):
    if paths.IS_WINDOWS:
        os.startfile(p)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def _reveal(p):
    if paths.IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
    else:
        _open_path(os.path.dirname(p))


def _read_clipboard():
    if not paths.IS_WINDOWS:
        return ""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
            capture_output=True, timeout=8, creationflags=NO_WINDOW)
        return out.stdout.decode("utf-8", errors="replace").strip()[:2000]
    except Exception:
        return ""


def _single_instance():
    if not paths.IS_WINDOWS:
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.CreateMutexW(None, False, "OQIDA_SINGLE_INSTANCE_MUTEX")
        if k.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mellowhq.OQIDA")
    except Exception:
        pass
    return True


def main():
    if not _single_instance():
        return
    import webview

    api = Api()
    index = paths.resource_dir() / "ui" / "index.html"
    window = webview.create_window(
        APP_NAME, url=index.as_uri(), js_api=api, width=940, height=700, min_size=(800, 580),
        background_color="#0b0d0c",
    )
    api._window = window
    window.events.closed += lambda: api._engine.shutdown()
    webview.start(private_mode=False, storage_path=str(paths.data_dir() / "webview"))


if __name__ == "__main__":
    main()
