"""OQIDA - 動画のURLからMP4/MP3を保存する個人用ソフト。"""
import json
import os
import subprocess
import sys
import threading

from core import downloader, paths, tools
from core import gif as gifmod
from core import sizefit
from core.netutil import is_newer
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
        self._yt_upd = YtdlpUpdater(
            self._engine.busy, get_skip=lambda: self._settings.get("ytdlp_skip"),
            on_installed=lambda: self._settings.set("ytdlp_skip", ""))
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
            "ytdlp": dict(self._yt_upd.snapshot(), current=tools.ytdlp_version_cached(),
                          previous=tools.previous_ytdlp_version(), skip=self._settings.get("ytdlp_skip")),
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
    def add_download(self, url, rng=None, force=False):
        """rng: 区間（{start, length}）。GIFでは必須、MP4/MP3などでは「区間を指定」がオンのときだけ渡される"""
        s = self._settings
        try:
            fmt = s.get("format")
            url = (url or "").strip()
            g = section = None
            if fmt == "gif":
                ri = rng or {}
                g = {"start": ri.get("start", ""), "length": ri.get("length", "10"),
                     "width": s.get("gif_width"), "fps": s.get("gif_fps")}
                gifmod.validate(g["start"], g["length"], g["width"], g["fps"])   # 先に確認して、画面に理由を返す
            elif rng:
                section = gifmod.validate_range(rng.get("start", ""), rng.get("length", ""))
            if not force and fmt != "gif":
                dup = self._engine.find_done(url, fmt)                        # 同じものを、もう一度落とそうとしていないか
                if dup:
                    return {"ok": False, "error": "duplicate", "title": dup["title"]}
            jid = self._engine.add(url, fmt, s.get("mp4_quality"), s.get("mp3_bitrate"), s.download_dir(), gif=g,
                                   size_limit=sizefit.limit_bytes(s.get("size_limit_mb")), section=section,
                                   save_thumb=s.get("save_thumb"))
            return {"ok": True, "id": jid}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def pause(self, job_id):
        self._engine.pause(job_id)

    def resume(self, job_id):
        self._engine.resume(job_id)

    def get_job_log(self, job_id):
        return self._engine.get_log(job_id)

    def copy_text(self, text):
        return {"ok": _write_clipboard(str(text or ""))}

    def clear_history(self):
        self._engine.clear_history()

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
            g = {"start": gi.get("start", ""), "length": gi.get("length", "10"),
                 "width": s.get("gif_width"), "fps": s.get("gif_fps")}
            v = gifmod.validate(g["start"], g["length"], g["width"], g["fps"])
            # 動画の長さを超えていたら、終わりに合わせて切り詰める。開始が動画の外なら、はっきりエラーにする
            ffdir = tools.ffmpeg_dir() if os.path.isfile(path or "") else None
            dur = gifmod.probe_duration(tools.ffprobe_exe(ffdir), path, tools.NO_WINDOW) if ffdir else None
            if dur:
                if v["start"] >= dur - 0.05:
                    raise ValueError("bad_range")
                if v["start"] + v["length"] > dur:
                    v["length"] = round(dur - v["start"], 3)
                    if v["length"] < gifmod.MIN_LENGTH:
                        raise ValueError("bad_range")
                g["start"], g["length"] = v["start"], v["length"]
            jid = self._engine.add_local(path, g, size_limit=sizefit.limit_bytes(s.get("size_limit_mb")))
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
        self._settings.set("ytdlp_skip", "")          # 手動で更新するときは、見送りを解除する
        self._yt_upd.update()

    def rollback_ytdlp(self):
        """yt-dlpを前の版に戻す（もう一度押すと、新しい版に戻る）"""
        if self._engine.busy():
            return {"ok": False, "error": "busy"}
        if not tools.previous_ytdlp_version():
            return {"ok": False, "error": "no_previous"}
        try:
            now, before = tools.rollback_ytdlp()
        except Exception:
            return {"ok": False, "error": "failed"}
        tools._ver_cache.update(path=None, mtime=None)            # 版の表示を取り直す
        # 古い版へ戻したときは、戻す前の（壊れている）版を自動更新で入れ直さないよう覚えておく
        if now and before and is_newer(before, now):
            self._settings.set("ytdlp_skip", before.lstrip("vV"))
        else:
            self._settings.set("ytdlp_skip", "")
        return {"ok": True, "current": now, "previous": before}

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


def _write_clipboard(text):
    """文字をクリップボードに入れる（ログのコピー用）"""
    if not paths.IS_WINDOWS:
        return False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::InputEncoding=[Text.Encoding]::UTF8; $t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t"],
            input=text.encode("utf-8"), capture_output=True, timeout=10, creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


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


def _webview2_installed():
    """画面表示に使うWebView2が入っているか（Windowsのみ）。確認できないときはTrue扱いで起動を続ける。"""
    if not paths.IS_WINDOWS:
        return True
    try:
        import winreg
    except Exception:
        return True
    key = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (key, key.replace(r"\WOW6432Node", "")):
            try:
                with winreg.OpenKey(root, sub) as k:
                    v, _ = winreg.QueryValueEx(k, "pv")
                    if v and v != "0.0.0.0":
                        return True
            except OSError:
                pass
    return False


def _warn_no_webview2():
    """WebView2が無いと画面が真っ白になるので、ダウンロード先を案内する。"""
    msg = ("OQIDA の画面表示に必要な「Microsoft Edge WebView2 ランタイム」が見つかりませんでした。\n"
           "下のページから無料で入手してインストールしたあと、OQIDA をもう一度起動してください。\n\n"
           "https://developer.microsoft.com/microsoft-edge/webview2/")
    try:
        import ctypes
        if ctypes.windll.user32.MessageBoxW(0, msg, "OQIDA", 0x40) == 0:
            raise OSError
    except Exception:
        try:
            import webbrowser
            webbrowser.open("https://developer.microsoft.com/microsoft-edge/webview2/")
        except Exception:
            pass


def main():
    if not _single_instance():
        return
    if not _webview2_installed():
        _warn_no_webview2()
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
