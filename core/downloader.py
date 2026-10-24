"""ダウンロードのキュー処理。yt-dlpを子プロセスとして動かして、出力を読み取る。"""
import itertools
import os
import re
import subprocess
import threading
import time

from . import paths, tools

URL_RE = re.compile(r"^https?://\S+$", re.I)

# yt-dlpの出力に付ける目印（アプリ側でこの行だけ読み取る）
P_TITLE = "OQIDA_TITLE|"
P_PROG = "OQIDA_PROG|"
P_PP = "OQIDA_PP|"
P_DONE = "OQIDA_DONE|"

ERROR_PATTERNS = [
    ("bot_check", ("confirm you're not a bot", "confirm you’re not a bot", "sign in to confirm")),
    ("age", ("age-restricted", "confirm your age", "inappropriate for some users")),
    ("private", ("private video", "members-only", "join this channel")),
    ("unavailable", ("video unavailable", "has been removed", "no longer available", "this video is not available",
                     "account associated with this video has been terminated")),
    ("geo", ("not available in your country", "geo restricted", "geo-restricted")),
    ("live", ("this live event", "premieres in", "live stream recording is not available")),
    ("unsupported", ("unsupported url", "is not a valid url")),
    ("ffmpeg", ("ffmpeg not found", "ffprobe and ffmpeg not found", "postprocessing:", "ffmpeg is not installed")),
    ("disk", ("no space left", "permission denied", "errno 28", "errno 13")),
    ("network", ("unable to download", "timed out", "temporary failure", "connection reset", "getaddrinfo failed",
                 "network is unreachable", "urlopen error", "http error 5", "remote end closed")),
    ("http403", ("http error 403",)),
]


def classify_error(text: str) -> str:
    low = text.lower()
    for code, needles in ERROR_PATTERNS:
        if any(n in low for n in needles):
            return code
    return "unknown"


def build_args(job, outdir, ytdlp, ffdir, deno, cookies_browser="none"):
    """yt-dlpに渡す引数を組み立てる（実行はしない。テストしやすいように分けてある）。"""
    a = [
        ytdlp,
        "--no-playlist", "--newline", "--progress", "--color", "never",
        "--windows-filenames", "--no-mtime",
        "-o", os.path.join(outdir, "%(title).150B.%(ext)s"),
        "--print", f"{P_TITLE}%(title)s",
        "--print", f"after_move:{P_DONE}%(filepath)s",
        "--progress-template",
        "download:" + P_PROG + "%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
        "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(progress.filename)s",
        "--progress-template", "postprocess:" + P_PP + "%(progress.postprocessor)s|%(progress.status)s",
    ]
    if ffdir:
        a += ["--ffmpeg-location", ffdir]
    if deno:
        a += ["--js-runtimes", f"deno:{deno}"]
    if cookies_browser and cookies_browser != "none":
        a += ["--cookies-from-browser", cookies_browser]

    if job["fmt"] == "mp3":
        a += ["-f", "ba/b", "-x", "--audio-format", "mp3",
              "--audio-quality", f"{job['bitrate']}K",
              "--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg"]
    else:
        q = job["quality"]
        sort = "res,vcodec:h264,acodec:m4a" if q == "best" else f"res:{q},vcodec:h264,acodec:m4a"
        a += ["-f", "bv*+ba/b", "-S", sort, "--merge-output-format", "mp4", "--embed-metadata"]
    a.append(job["url"])
    return a


def _num(s):
    try:
        v = float(s)
        return v if v == v else 0.0
    except (TypeError, ValueError):
        return 0.0


class Engine:
    def __init__(self, settings, tool_provider=None):
        self.settings = settings
        self.tools = tool_provider or {
            "ytdlp": tools.ytdlp_path, "ffdir": tools.ffmpeg_dir, "deno": tools.deno_path,
        }
        self._jobs = []
        self._ids = itertools.count(1)
        self._cv = threading.Condition()
        self._procs = {}
        self._stop = False
        self._busy = False
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------------------------------------------------------- 公開操作
    def add(self, url, fmt, quality, bitrate, outdir):
        url = (url or "").strip()
        if not URL_RE.match(url):
            raise ValueError("bad_url")
        job = {
            "id": next(self._ids), "url": url, "fmt": fmt, "quality": quality, "bitrate": bitrate,
            "outdir": outdir, "status": "queued", "title": "", "percent": 0.0, "speed": 0.0, "eta": 0,
            "filepath": "", "error": "", "error_detail": "", "created": time.time(),
            "_cancel": False, "_streams": [],
        }
        with self._cv:
            self._jobs.append(job)
            self._cv.notify()
        return job["id"]

    def snapshot(self):
        with self._cv:
            return [{k: v for k, v in j.items() if not k.startswith("_")} for j in self._jobs]

    def busy(self):
        with self._cv:
            return self._busy or any(j["status"] in ("queued", "running") for j in self._jobs)

    def _find(self, jid):
        return next((j for j in self._jobs if j["id"] == jid), None)

    def cancel(self, jid):
        with self._cv:
            j = self._find(jid)
            if not j:
                return
            j["_cancel"] = True
            if j["status"] == "queued":
                j["status"] = "canceled"
            p = self._procs.get(jid)
        if p:
            try:
                p.terminate()
            except Exception:
                pass

    def remove(self, jid):
        with self._cv:
            j = self._find(jid)
            if j and j["status"] not in ("running",):
                self._jobs.remove(j)

    def retry(self, jid):
        with self._cv:
            j = self._find(jid)
            if j and j["status"] in ("error", "canceled"):
                j.update(status="queued", percent=0.0, speed=0.0, eta=0, error="", error_detail="",
                         _cancel=False, _streams=[])
                self._cv.notify()

    def clear_finished(self):
        with self._cv:
            self._jobs = [j for j in self._jobs if j["status"] in ("queued", "running")]

    def shutdown(self):
        with self._cv:
            self._stop = True
            for j in self._jobs:
                j["_cancel"] = True
            procs = list(self._procs.values())
            self._cv.notify_all()
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass

    # ---------------------------------------------------------- 内部処理
    def _worker(self):
        while True:
            with self._cv:
                while not self._stop and not any(j["status"] == "queued" for j in self._jobs):
                    self._cv.wait()
                if self._stop:
                    return
                job = next(j for j in self._jobs if j["status"] == "queued")
                job["status"] = "running"
                self._busy = True
            try:
                self._run(job)
            except Exception as e:  # noqa: BLE001
                self._fail(job, "unknown", str(e))
            finally:
                with self._cv:
                    self._busy = False

    def _fail(self, job, code, detail=""):
        with self._cv:
            job["status"] = "error"
            job["error"] = code
            job["error_detail"] = detail[-600:]

    def _run(self, job):
        ytdlp = self.tools["ytdlp"]()
        ffdir = self.tools["ffdir"]()
        deno = self.tools["deno"]()
        if not ytdlp or not ffdir:
            return self._fail(job, "tools_missing")
        os.makedirs(job["outdir"], exist_ok=True)
        args = build_args(job, job["outdir"], ytdlp, ffdir, deno, self.settings.get("cookies_browser"))
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                             creationflags=tools.NO_WINDOW, stdin=subprocess.DEVNULL)
        with self._cv:
            self._procs[job["id"]] = p
        tail, saw_error = [], []
        try:
            for raw in p.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                self._on_line(job, line)
                if line.startswith("ERROR:"):
                    saw_error.append(line)
                tail.append(line)
                tail = tail[-12:]
            rc = p.wait()
        finally:
            with self._cv:
                self._procs.pop(job["id"], None)

        with self._cv:
            canceled = job["_cancel"]
        if canceled:
            with self._cv:
                job["status"] = "canceled"
            return
        if rc == 0 and job["filepath"]:
            with self._cv:
                job.update(status="done", percent=100.0, speed=0.0, eta=0)
            return
        text = "\n".join(saw_error) or "\n".join(tail)
        self._fail(job, classify_error(text), text)

    def _on_line(self, job, line):
        with self._cv:
            if line.startswith(P_TITLE):
                job["title"] = line[len(P_TITLE):]
            elif line.startswith(P_DONE):
                job["filepath"] = line[len(P_DONE):]
            elif line.startswith(P_PROG):
                f = line[len(P_PROG):].split("|", 6)
                if len(f) < 7:
                    return
                status, done, total, est, speed, eta, fname = f
                total_b = _num(total) or _num(est)
                frac = (_num(done) / total_b) if total_b else 0.0
                frac = min(max(frac, 0.0), 1.0)
                if fname not in job["_streams"]:
                    job["_streams"].append(fname)
                idx = job["_streams"].index(fname)
                if job["fmt"] == "mp4":
                    pct = 90 * frac if idx == 0 else 90 + 5 * frac
                else:
                    pct = 95 * frac
                if status == "finished":
                    pct = max(pct, 90 if (job["fmt"] == "mp4" and idx == 0) else 95)
                job["percent"] = max(job["percent"], min(pct, 95.0))
                job["speed"] = _num(speed)
                job["eta"] = int(_num(eta))
            elif line.startswith(P_PP):
                f = line[len(P_PP):].split("|", 1)
                if len(f) == 2 and f[1] == "started":
                    job["status"] = "running"
                    job["speed"] = 0.0
                    job["eta"] = 0
                    job["percent"] = max(job["percent"], 95.0)
