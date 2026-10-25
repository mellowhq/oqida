"""動画プレイヤー用の、ごく小さなローカル配信サーバー。
パソコン内の選んだ動画を、アプリの画面（<video>）が再生できるよう 127.0.0.1 で出すだけ。
外（LAN）には出さない。シーク（途中への移動）のため Range リクエストに対応する。"""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_MIME = {
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".webm": "video/webm",
    ".avi": "video/x-msvideo", ".m4v": "video/mp4", ".flv": "video/x-flv", ".wmv": "video/x-ms-wmv",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".opus": "audio/ogg", ".flac": "audio/flac", ".wav": "audio/wav",
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _serve(self, head_only=False):
        srv = self.server
        path, token = srv.current_path, srv.token
        # ?t=トークン を照合（他のアプリが勝手に読めないように）
        q = self.path.split("?", 1)
        want = ""
        if len(q) == 2:
            for kv in q[1].split("&"):
                if kv.startswith("t="):
                    want = kv[2:]
        if not path or not os.path.isfile(path) or want != token:
            self.send_response(404)
            self.end_headers()
            return
        size = os.path.getsize(path)
        ctype = _MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if rng and rng.startswith("bytes="):
            try:
                s, e = rng[6:].split("-", 1)
                start = int(s) if s else 0
                end = int(e) if e else size - 1
                end = min(end, size - 1)
                status = 206
            except ValueError:
                start, end, status = 0, size - 1, 200
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                left -= len(chunk)

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)


class MediaServer:
    """選んだ1ファイルだけを配信する。set_file() で切り替え、url() で再生URLを得る。"""

    def __init__(self):
        self._srv = None
        self._port = 0
        self._token = ""
        self._lock = threading.Lock()

    def _ensure(self):
        if self._srv is not None:
            return
        import secrets
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._srv.current_path = None
        self._srv.token = self._token = secrets.token_urlsafe(12)
        self._port = self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def set_file(self, path):
        """再生するファイルを設定し、再生URLを返す。ファイルが無ければ None。"""
        if not path or not os.path.isfile(path):
            return None
        with self._lock:
            self._ensure()
            self._srv.current_path = path
            import time
            # ?v= はキャッシュ避け（別ファイルに切り替えたとき確実に読み直させる）
            return f"http://127.0.0.1:{self._port}/media?t={self._token}&v={int(time.time() * 1000)}"

    def stop(self):
        if self._srv is not None:
            try:
                self._srv.shutdown()
            except Exception:
                pass
            self._srv = None
