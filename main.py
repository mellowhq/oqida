"""OQIDA - 動画のURLからMP4/MP3を保存する個人用ソフト。"""
import json
import os
import subprocess
import sys
import threading

from core import downloader, paths, tools
from core import gif as gifmod
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
    def add_download(self, url, gif=None):
        s = self._settings
        try:
            fmt = s.get("format")
            g = None
            if fmt == "gif":
                gi = gif or {}
                g = {"start": gi.get("start", ""), "length": gi.get("length", "10"),
                     "width": s.get("gif_width"), "fps": s.get("gif_fps")}
                gifmod.validate(g["start"], g["length"], g["width"], g["fps"])   # 先に確認して、画面に理由を返す
            jid = self._engine.add(url, fmt, s.get("mp4_quality"), s.get("mp3_bitrate"), s.download_dir(), gif=g)
            return {"ok": True, "id": jid}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------ GIF変換（パソコン内の動画）
    def pick_video(self):
        import webview
        fd = getattr(webview, "FileDialog", None)
        kind = fd.OPEN if fd is not None else webview.OPEN_DIALOG
        types = ("動画ファイル (*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.flv;*.wmv)", "すべてのファイル (*.*)")
        res = self._window.create_file_dialog(kind, allow_multiple=False, file_types=types)
        if not res:
            return {"ok": False, "error": "canceled"}
        return self.inspect_video(res[0] if isinstance(res, (list, tuple)) else res)

    def inspect_video(self, path):
        """選んだファイルの名前と長さを返す"""
        if not isinstance(path, str) or not os.path.isfile(path):
            return {"ok": False, "error": "bad_file"}
        ffdir = tools.ffmpeg_dir()
        dur = gifmod.probe_duration(tools.ffprobe_exe(ffdir), path, tools.NO_WINDOW) if ffdir else None
        return {"ok": True, "path": path, "name": os.path.basename(path), "duration": dur}

    def convert_gif(self, path, gif=None):
        s = self._settings
        gi = gif or {}
        try:
            jid = self._engine.add_local(path, {"start": gi.get("start", ""), "length": gi.get("length", "10"),
                                                "width": s.get("gif_width"), "fps": s.get("gif_fps")})
            return {"ok": True, "id": jid}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def _on_drop(self, path):
        """ウィンドウへのドラッグ＆ドロップ（試験的）。選ばれたファイルの情報を画面へ渡す"""
        info = self.inspect_video(path)
        if self._window is not None:
            self._window.evaluate_js("window.onFileDropped && window.onFileDropped(" + json.dumps(info) + ")")

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

    def bind_drop():
        # 動画ファイルのドラッグ＆ドロップ。使えない環境では何もしない（「ファイルを選ぶ」は常に使える）
        try:
            from webview.dom import DOMEventHandler

            def on_drop(e):
                files = (e.get("dataTransfer") or {}).get("files") or []
                path = files[0].get("pywebviewFullPath") if files else None
                if path:
                    api._on_drop(path)

            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            pass

    window.events.loaded += bind_drop
    webview.start(private_mode=False, storage_path=str(paths.data_dir() / "webview"))


if __name__ == "__main__":
    main()
