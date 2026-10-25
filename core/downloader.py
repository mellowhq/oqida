"""ダウンロードのキュー処理。yt-dlpを子プロセスとして動かして、出力を読み取る。"""
import itertools
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import gif as gifmod
from . import history, paths, sizefit, tools
from .version import __version__

URL_RE = re.compile(r"^https?://\S+$", re.I)
AUDIO_FORMATS = ("mp3", "m4a", "opus", "flac", "wav")
LOSSY_AUDIO = ("mp3", "m4a", "opus")
FORMATS = ("mp4", "gif") + AUDIO_FORMATS
FINAL = history.FINAL
LOG_LINES = 500

# yt-dlpの出力に付ける目印（アプリ側でこの行だけ読み取る）
P_TITLE = "OQIDA_TITLE|"
P_SITE = "OQIDA_SITE|"
P_THUMB = "OQIDA_THUMB|"
P_PROG = "OQIDA_PROG|"
P_PP = "OQIDA_PP|"
P_DONE = "OQIDA_DONE|"

ERROR_PATTERNS = [
    ("bot_check", ("confirm you're not a bot", "confirm you’re not a bot", "sign in to confirm")),
    ("age", ("age-restricted", "confirm your age", "inappropriate for some users")),
    ("login", ("login required", "requires authentication", "need to log in", "log in to", "please log in",
               "nsfw tweet", "rate-limit reached")),
    ("no_video", ("no video could be found", "there is no video", "no video formats found")),
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


def build_args(job, outdir, ytdlp, ffdir, deno, cookies_browser="none", speed_limit="0"):
    """yt-dlpに渡す引数を組み立てる（実行はしない。テストしやすいように分けてある）。"""
    section = job.get("section")
    suffix = gifmod.range_suffix(section) if section else ""          # 区間を指定したときは、ファイル名に印を付ける
    a = [
        ytdlp,
        "--no-playlist", "--newline", "--progress", "--color", "never",
        "--windows-filenames", "--no-mtime",
        "-o", os.path.join(outdir, "%(title).150B" + suffix + ".%(ext)s"),
        "--print", f"{P_TITLE}%(title)s",
        "--print", f"{P_SITE}%(webpage_url_domain)s",
        "--print", f"{P_THUMB}%(thumbnail)s",
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
    if speed_limit and str(speed_limit) != "0":
        a += ["--limit-rate", f"{speed_limit}M"]

    fmt = job["fmt"]
    embed_thumb = False
    if fmt == "gif":
        # GIFには高画質は要らないので720p以下を、指定区間だけ取ってくる（長い動画でも速い）
        a += ["-f", "bv*[height<=720]/b[height<=720]/bv*/b",
              "--download-sections", gifmod.section_arg(job["gif"]), "--force-keyframes-at-cuts"]
    elif fmt in AUDIO_FORMATS:
        pick = {"m4a": "ba[ext=m4a]/ba/b", "opus": "ba[acodec=opus]/ba/b"}.get(fmt, "ba/b")
        a += ["-f", pick, "-x", "--audio-format", fmt, "--embed-metadata"]
        if fmt in LOSSY_AUDIO:
            a += ["--audio-quality", f"{job['bitrate']}K"]
        embed_thumb = fmt in ("mp3", "m4a") and not job.get("size_limit")   # 上限があるときは、ジャケット画像の分も節約する
        if section:
            a += ["--download-sections", gifmod.section_arg(section), "--force-keyframes-at-cuts"]
    else:
        q = job["quality"]
        lim = job.get("size_limit", 0)
        if q == "best" and lim:      # 小さい上限なのに4Kを落とすのは無駄なので、元の画質に上限をつける
            q = "720" if lim <= 25 * sizefit.MB else "1080" if lim <= 100 * sizefit.MB else "best"
        sort = "res,vcodec:h264,acodec:m4a" if q == "best" else f"res:{q},vcodec:h264,acodec:m4a"
        a += ["-f", "bv*+ba/b", "-S", sort, "--merge-output-format", "mp4", "--embed-metadata"]
        if section:
            a += ["--download-sections", gifmod.section_arg(section), "--force-keyframes-at-cuts"]
    want_thumb = bool(job.get("save_thumb")) and fmt != "gif"
    if embed_thumb:
        a += ["--embed-thumbnail"]
    if want_thumb:
        a += ["--write-thumbnail"]
    if embed_thumb or want_thumb:
        a += ["--convert-thumbnails", "jpg"]
    a.append(job["url"])
    return a


AUDIO_CODECS = {"mp3": "libmp3lame", "m4a": "aac", "opus": "libopus", "flac": "flac", "wav": "pcm_s16le"}


def build_convert_args(ffmpeg, src, dst, fmt, bitrate="320", trim=None):
    """パソコン内の動画/音声ファイルを、別の形式に変換するffmpeg引数。trim=(開始秒,長さ秒)で区間切り出し。"""
    cut = ["-ss", f"{trim[0]:g}", "-t", f"{trim[1]:g}"] if trim else []
    base = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", *cut, "-i", src]
    if fmt == "mp4":
        return base + ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst]
    a = base + ["-vn", "-c:a", AUDIO_CODECS[fmt], "-map_metadata", "0"]
    if fmt in ("mp3", "m4a", "opus"):
        br = min(int(bitrate), 256) if fmt == "opus" else int(bitrate)   # Opusは256kまで
        a += ["-b:a", f"{br}k"]
    return a + [dst]


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
        self._active = 0          # いま動いているジョブ数
        self._load_history()
        for _ in range(4):        # ワーカーを複数用意し、同時実行数は設定で絞る（既定は1＝順番に）
            threading.Thread(target=self._worker, daemon=True).start()

    # ---------------------------------------------------------- 公開操作
    def _new_job(self, **kw):
        job = {
            "id": next(self._ids), "url": "", "fmt": "mp4", "quality": "best", "bitrate": "320", "kind": "download",
            "outdir": "", "gif": None, "section": None, "save_thumb": False, "size_limit": 0, "size": 0, "fitted": False,
            "stage": "", "status": "queued", "title": "", "site": "", "thumb": "", "percent": 0.0, "speed": 0.0, "eta": 0,
            "filepath": "", "error": "", "error_detail": "", "created": time.time(),
            "_cancel": False, "_pause": False, "_streams": [], "_log": [],
        }
        job.update(kw)
        return job

    def add(self, url, fmt, quality, bitrate, outdir, gif=None, size_limit=0, section=None, save_thumb=False):
        url = (url or "").strip()
        if not URL_RE.match(url):
            raise ValueError("bad_url")
        if fmt not in FORMATS:
            raise ValueError("bad_format")
        if fmt == "gif":
            if not isinstance(gif, dict):
                raise ValueError("bad_gif")
            gif = gifmod.validate(gif.get("start"), gif.get("length"), gif.get("width"), gif.get("fps"))
            section = None
        else:
            gif = None
            if section is not None:
                if not isinstance(section, dict):
                    raise ValueError("bad_range")
                section = gifmod.validate_range(section.get("start"), section.get("length"))
        job = self._new_job(url=url, fmt=fmt, quality=quality, bitrate=str(bitrate), outdir=outdir, gif=gif,
                            section=section, save_thumb=bool(save_thumb) and fmt != "gif", size_limit=int(size_limit or 0))
        with self._cv:
            self._jobs.append(job)
            self._cv.notify()
        return job["id"]

    def add_local(self, src, gif, size_limit=0):
        """パソコン内の動画ファイルを、そのままGIFに変換する（ダウンロードなし）。GIFは元のファイルと同じフォルダに保存。"""
        if not isinstance(src, str) or not os.path.isfile(src):
            raise ValueError("bad_file")
        if not isinstance(gif, dict):
            raise ValueError("bad_gif")
        g = gifmod.validate(gif.get("start"), gif.get("length"), gif.get("width"), gif.get("fps"))
        job = self._new_job(url=src, fmt="gif", quality="", bitrate="", kind="convert",
                            outdir=os.path.dirname(os.path.abspath(src)), gif=g, size_limit=int(size_limit or 0),
                            title=os.path.splitext(os.path.basename(src))[0])
        with self._cv:
            self._jobs.append(job)
            self._cv.notify()
        return job["id"]

    def add_transcode(self, src, fmt, section=None, size_limit=0):
        """パソコン内の動画/音声を、別の形式(mp4/mp3/m4a/opus/flac/wav)に変換する。元と同じフォルダに保存。"""
        if not isinstance(src, str) or not os.path.isfile(src):
            raise ValueError("bad_file")
        if fmt not in AUDIO_CODECS and fmt != "mp4":
            raise ValueError("bad_format")
        if section is not None:
            if not isinstance(section, dict):
                raise ValueError("bad_range")
            section = gifmod.validate_range(section.get("start"), section.get("length"))
        job = self._new_job(url=src, fmt=fmt, quality="", bitrate=str(self.settings.get("mp3_bitrate")),
                            kind="transcode", outdir=os.path.dirname(os.path.abspath(src)), section=section,
                            size_limit=int(size_limit or 0), title=os.path.splitext(os.path.basename(src))[0])
        with self._cv:
            self._jobs.append(job)
            self._cv.notify()
        return job["id"]

    # ---------------------------------------------------------- 履歴
    def _history_on(self):
        try:
            return bool(self.settings.get("history_keep"))
        except Exception:
            return False

    def _load_history(self):
        if not self._history_on():
            return
        for e in history.load():
            job = self._new_job(**e)
            job["percent"] = 100.0 if job["status"] == "done" else 0.0
            self._jobs.append(job)

    def _persist(self):
        if not self._history_on():
            return
        with self._cv:
            entries = [{k: j.get(k) for k in history.KEYS} for j in self._jobs if j["status"] in FINAL]
        try:
            history.save(entries)
        except OSError:
            pass                                                          # 保存できなくても、ダウンロード自体は止めない

    def clear_history(self):
        """終わったものを一覧から消し、履歴ファイルも消す"""
        self.clear_finished()
        history.delete_file()

    def find_done(self, url, fmt):
        """同じURL・同じ形式で、すでに保存済み（ファイルも残っている）のものを探す"""
        with self._cv:
            for j in reversed(self._jobs):
                if (j["status"] == "done" and j["url"] == url and j["fmt"] == fmt and j["kind"] == "download"
                        and j["filepath"] and os.path.exists(j["filepath"])):
                    return {k: v for k, v in j.items() if not k.startswith("_")}
        return None

    # ---------------------------------------------------------- ログ
    @staticmethod
    def _redact(text):
        home = str(Path.home())
        return text.replace(home, "~") if home else text

    def _log(self, job, line):
        with self._cv:
            buf = job["_log"]
            buf.append(self._redact(line))
            if len(buf) > LOG_LINES:
                del buf[: len(buf) - LOG_LINES]

    def get_log(self, jid):
        """失敗の原因を調べるための文章（コピーして共有できる）"""
        ver = tools.ytdlp_version_cached() or tools.ytdlp_version() or "?"      # 時間がかかることがあるので、ロックの外で調べる
        with self._cv:
            j = self._find(jid)
            if not j:
                return ""
            head = [
                f"OQIDA {__version__} / yt-dlp {ver} / {os.name} {sys.platform}",
                f"site: {j['site'] or '-'} / format: {j['fmt']} / status: {j['status']} / error: {j['error'] or '-'}",
                f"url: {self._redact(j['url'])}",
            ]
            body = list(j["_log"]) or ([self._redact(j["error_detail"])] if j["error_detail"] else [])
            return "\n".join(head + [""] + body)

    # ---------------------------------------------------------- 一時停止・再開
    def pause(self, jid):
        """ダウンロード中のものを止める（途中までのファイルは残り、再開すると続きから）"""
        with self._cv:
            j = self._find(jid)
            if not j or j["kind"] != "download":
                return
            if j["status"] == "queued":
                j["status"] = "paused"
                return
            if j["status"] != "running" or j["stage"] == "convert":
                return
            j["_pause"] = True
            p = self._procs.get(jid)
        if p:
            try:
                p.terminate()
            except Exception:
                pass

    def resume(self, jid):
        with self._cv:
            j = self._find(jid)
            if j and j["status"] == "paused":
                j.update(status="queued", _pause=False, _streams=[])
                self._cv.notify()

    def snapshot(self):
        with self._cv:
            return [{k: v for k, v in j.items() if not k.startswith("_")} for j in self._jobs]

    def busy(self):
        with self._cv:
            return self._active > 0 or any(j["status"] in ("queued", "running") for j in self._jobs)

    def _parallel_limit(self):
        try:
            return max(1, min(4, int(self.settings.get("max_parallel"))))
        except (ValueError, TypeError):
            return 1

    def _find(self, jid):
        return next((j for j in self._jobs if j["id"] == jid), None)

    def cancel(self, jid):
        with self._cv:
            j = self._find(jid)
            if not j:
                return
            j["_cancel"] = True
            if j["status"] in ("queued", "paused"):
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
        self._persist()

    def retry(self, jid):
        with self._cv:
            j = self._find(jid)
            if j and j["status"] in ("error", "canceled"):
                j.update(status="queued", stage="", size=0, fitted=False, percent=0.0, speed=0.0, eta=0, error="",
                         error_detail="", filepath="", _cancel=False, _pause=False, _streams=[], _log=[])
                self._cv.notify()

    def clear_finished(self):
        with self._cv:
            self._jobs = [j for j in self._jobs if j["status"] not in FINAL]
        self._persist()

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
                # 待機中のジョブがあり、かつ同時実行の上限に余裕があるまで待つ
                while not self._stop and not (
                    self._active < self._parallel_limit() and any(j["status"] == "queued" for j in self._jobs)
                ):
                    self._cv.wait(timeout=0.5)       # 上限が変わることもあるので、時々見直す
                if self._stop:
                    return
                job = next((j for j in self._jobs if j["status"] == "queued"), None)
                if job is None:
                    continue
                job["status"] = "running"
                self._active += 1
            try:
                self._run(job)
            except Exception as e:  # noqa: BLE001
                self._log(job, f"[OQIDA] unexpected error: {e!r}")
                self._fail(job, "unknown", str(e))
            finally:
                with self._cv:
                    self._active -= 1
                    self._cv.notify_all()
                self._persist()

    def _fail(self, job, code, detail=""):
        self._log(job, f"[OQIDA] failed: {code}" + (f" / {detail[-300:]}" if detail else ""))
        with self._cv:
            job["status"] = "error"
            job["error"] = code
            job["error_detail"] = detail[-600:]

    def _canceled(self, job):
        with self._cv:
            return job["_cancel"]

    def _run(self, job):
        ffdir = self.tools["ffdir"]()
        if job.get("kind") == "convert":                       # パソコン内の動画 → GIF
            if not ffdir:
                return self._fail(job, "tools_missing")
            g = job["gif"]
            return self._finish_gif(job, ffdir, src=job["url"], trim=(g["start"], g["length"]),
                                    lo=0.0, span=99.0, fail_code="convert")
        if job.get("kind") == "transcode":                     # パソコン内の動画/音声 → 別の形式
            if not ffdir:
                return self._fail(job, "tools_missing")
            return self._convert_file(job, ffdir)
        ytdlp = self.tools["ytdlp"]()
        deno = self.tools["deno"]()
        if not ytdlp or not ffdir:
            return self._fail(job, "tools_missing")
        os.makedirs(job["outdir"], exist_ok=True)
        workdir = None
        target = job["outdir"]
        if job["fmt"] == "gif":
            # 途中の動画は作業フォルダに置いて、保存先にはGIFだけを出す
            workdir = str(paths.tmp_dir() / f"gif{job['id']}_{int(time.time())}")
            os.makedirs(workdir, exist_ok=True)
            target = workdir
        try:
            self._run_ytdlp(job, ytdlp, ffdir, deno, target)
            if job["status"] == "running":                     # ダウンロード成功。ここから仕上げ
                if job["fmt"] == "gif":
                    self._finish_gif(job, ffdir)
                else:
                    self._finish_media(job, ffdir)
        finally:
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)

    def _run_ytdlp(self, job, ytdlp, ffdir, deno, outdir):
        args = build_args(job, outdir, ytdlp, ffdir, deno, self.settings.get("cookies_browser"),
                          self.settings.get("speed_limit"))
        shown, skip = [], False
        for x in args:                                          # アプリ内部用の長い指定は、ログを読みにくくするだけなので省く
            if skip:
                skip = False
            elif x in ("--print", "--progress-template"):
                skip = True
            else:
                shown.append(x)
        self._log(job, "$ " + " ".join(shown))
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
                if not line.startswith((P_PROG, P_PP)):        # 進み具合の行は、ログが読みにくくなるので載せない
                    self._log(job, line)
                if line.startswith("ERROR:"):
                    saw_error.append(line)
                tail.append(line)
                tail = tail[-12:]
            rc = p.wait()
        finally:
            with self._cv:
                self._procs.pop(job["id"], None)
        if self._canceled(job):
            with self._cv:
                job["status"] = "canceled"
            return
        if rc == 0 and job["filepath"]:
            with self._cv:
                job["_pause"] = False
            return                                              # 成功。完了にするのは仕上げ（サイズ調整）のあと
        with self._cv:
            paused = job["_pause"]
        if paused:                                              # 一時停止。途中までのファイルは残してあるので、再開すると続きから
            with self._cv:
                job.update(status="paused", speed=0.0, eta=0, _pause=False)
            self._log(job, "[OQIDA] paused")
            return
        text = "\n".join(saw_error) or "\n".join(tail)
        self._fail(job, classify_error(text), text)

    def _ffmpeg(self, job, args, total_sec, lo, span):
        """ffmpegを動かして、進み具合を job["percent"] に反映する。返り値: (終了コード, 最後のメッセージ)"""
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=tools.NO_WINDOW, stdin=subprocess.DEVNULL)
        with self._cv:
            self._procs[job["id"]] = p
        tail = []
        try:
            for raw in p.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                sec = gifmod.progress_seconds(line)
                if sec is not None:
                    frac = min(1.0, sec / max(total_sec, 0.1))
                    with self._cv:
                        job["percent"] = max(job["percent"], min(99.0, lo + span * frac))
                elif line and "=" not in line:
                    tail.append(line)
                    tail = tail[-8:]
                    self._log(job, "[ffmpeg] " + line)
            rc = p.wait()
        finally:
            with self._cv:
                self._procs.pop(job["id"], None)
        return rc, tail

    @staticmethod
    def _remove(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _convert_file(self, job, ffdir):
        """パソコン内のファイルを別の形式に変換して、元と同じフォルダに保存する"""
        src = job["url"]
        fmt = job["fmt"]
        stem = os.path.splitext(os.path.basename(src))[0]
        trim = None
        if job.get("section"):
            sec = job["section"]
            dur = gifmod.probe_duration(tools.ffprobe_exe(ffdir), src, tools.NO_WINDOW)
            start, length = sec["start"], sec["length"]
            if dur:
                if start >= dur - 0.05:
                    return self._fail(job, "bad_range", "start is past the end of the file")
                if start + length > dur:
                    length = round(dur - start, 3)
            trim = (start, length)
            stem += gifmod.range_suffix({"start": start, "length": length})
        dst = gifmod.unique_path(job["outdir"], stem, "." + fmt)
        dur_total = (trim[1] if trim else gifmod.probe_duration(tools.ffprobe_exe(ffdir), src, tools.NO_WINDOW)) or 1
        with self._cv:
            job.update(stage="convert", speed=0.0, eta=0)
            job["percent"] = max(job["percent"], 2.0)
        args = build_convert_args(tools.ffmpeg_exe(ffdir), src, dst, fmt, job["bitrate"], trim)
        rc, tail = self._ffmpeg(job, args, dur_total, 2.0, 92.0)
        if self._canceled(job):
            self._remove(dst)
            with self._cv:
                job["status"] = "canceled"
            return
        if rc != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            self._remove(dst)
            return self._fail(job, "convert", "\n".join(tail))
        job["filepath"] = dst
        self._finish_media(job, ffdir)          # サイズ上限があれば、ここで収める

    def _finish_media(self, job, ffdir):
        """MP4/MP3の仕上げ。サイズ上限があって超えていたら、収まるように作り直してから完了にする"""
        path = job["filepath"]
        limit = job.get("size_limit", 0)
        try:
            size = os.path.getsize(path)
        except OSError:
            return self._fail(job, "unknown", "output file is missing")
        if limit and size > limit:
            if not self._shrink(job, ffdir, path, limit):
                return                                          # 失敗・中止の状態は _shrink が設定済み
            size = os.path.getsize(path)
        with self._cv:
            job.update(status="done", percent=100.0, speed=0.0, eta=0, stage="", size=size)

    def _shrink(self, job, ffdir, path, limit):
        """できあがったMP4・音声を、長さから逆算した設定で作り直して上限に収める。成功したら True"""
        ff = tools.ffmpeg_exe(ffdir)
        fmt = job["fmt"]
        if fmt in ("flac", "wav"):                              # ロスレスは、音質を下げずに小さくはできない
            self._fail(job, "size_fail", "lossless audio cannot be fitted; choose MP3, M4A or Opus")
            return False
        dur = gifmod.probe_duration(tools.ffprobe_exe(ffdir), path, tools.NO_WINDOW)
        if not dur:
            self._fail(job, "size_fail", "could not read the duration")
            return False
        with self._cv:
            job.update(stage="convert", speed=0.0, eta=0, fitted=True)
        tmp = path + ".fit" + (os.path.splitext(path)[1] or ".tmp")
        is_audio = fmt in LOSSY_AUDIO
        if is_audio:
            first = sizefit.mp3_bitrate_for(dur, limit, int(job["bitrate"] or 320))
            if not first:
                self._fail(job, "size_fail", "even the lowest bitrate does not fit")
                return False
            settings = [b for b in sizefit.MP3_LADDER if b <= first][:2]     # まず計算どおり、だめならもう1段下げる
            codec = {"mp3": "libmp3lame", "m4a": "aac", "opus": "libopus"}[fmt]
        else:
            plan = sizefit.video_plan(dur, limit)
            if not plan:
                self._fail(job, "size_fail", "the limit is too small for this length")
                return False
            settings = [plan]
        i, sz = 0, 0
        while i < len(settings) or (not is_audio and i < 3):
            cur = settings[i]
            if is_audio:
                bk = min(cur, 256) if fmt == "opus" else cur                 # Opusは256kまで
                args = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-i", path,
                        "-vn", "-c:a", codec, "-b:a", f"{bk}k", "-map_metadata", "0", tmp]
            else:
                v = cur["v_kbps"]
                args = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-i", path,
                        "-vf", f"scale=-2:'min({cur['height']},ih)'", "-c:v", "libx264", "-preset", "medium",
                        "-b:v", f"{v}k", "-maxrate", f"{int(v * 1.15)}k", "-bufsize", f"{v * 2}k", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", f"{cur['a_kbps']}k", "-movflags", "+faststart", tmp]
            rc, tail = self._ffmpeg(job, args, dur, 95.0, 4.0)
            if self._canceled(job):
                self._remove(tmp)
                with self._cv:
                    job["status"] = "canceled"
                return False
            if rc != 0 or not os.path.exists(tmp):
                self._remove(tmp)
                self._fail(job, "ffmpeg", "\n".join(tail))
                return False
            sz = os.path.getsize(tmp)
            if sz <= limit:
                os.replace(tmp, path)
                return True
            i += 1
            if not is_audio and i < 3:
                nxt = sizefit.retry_video_plan(cur, sz, limit)
                if not nxt:
                    break
                settings.append(nxt)
        self._remove(tmp)
        self._fail(job, "size_fail", f"{sz} bytes > limit {limit}")
        return False

    def _finish_gif(self, job, ffdir, src=None, trim=None, lo=60.0, span=39.0, fail_code="ffmpeg"):
        """動画をGIFにする。サイズ上限があって超えたら、幅・色数・コマ数を下げて作り直す（最大7回）"""
        g = job["gif"]
        limit = job.get("size_limit", 0)
        src = src or job["filepath"]
        stem = os.path.splitext(os.path.basename(src))[0]
        dst = gifmod.unique_path(job["outdir"], stem, ".gif")
        cur = {"width": g["width"], "fps": g["fps"], "colors": 256}
        with self._cv:
            job.update(stage="convert", speed=0.0, eta=0, status="running")
            job["percent"] = max(job["percent"], lo)
        for attempt in range(1, sizefit.MAX_GIF_ATTEMPTS + 1):
            args = gifmod.build_ffmpeg_args(tools.ffmpeg_exe(ffdir), src, dst, cur["fps"], cur["width"],
                                            trim=trim, colors=cur["colors"])
            part = min(attempt - 1, 3)
            rc, tail = self._ffmpeg(job, args, g["length"], lo + span * part / 4, span / 4)
            ok = rc == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
            if self._canceled(job):
                self._remove(dst)
                with self._cv:
                    job["status"] = "canceled"
                return
            if not ok:
                self._remove(dst)
                return self._fail(job, fail_code, "\n".join(tail))
            size = os.path.getsize(dst)
            if not limit or size <= limit:
                with self._cv:
                    job.update(status="done", percent=100.0, speed=0.0, eta=0, filepath=dst, stage="", size=size)
                    job["fitted"] = attempt > 1
                return
            dims = gifmod.gif_dimensions(dst)
            nxt = sizefit.next_gif_params(cur, dims[0] if dims else cur["width"], size, limit, attempt)
            if nxt is None:
                break
            cur = nxt
            with self._cv:
                job["fitted"] = True
        self._remove(dst)
        self._fail(job, "size_fail", f"could not fit within {limit} bytes")

    def _on_line(self, job, line):
        with self._cv:
            if line.startswith(P_TITLE):
                job["title"] = line[len(P_TITLE):]
            elif line.startswith(P_SITE):
                dom = line[len(P_SITE):].strip().lower().split(":")[0]
                for pre in ("www.", "m.", "mobile."):
                    if dom.startswith(pre):
                        dom = dom[len(pre):]
                job["site"] = "" if dom in ("na", "none") else dom
            elif line.startswith(P_THUMB):
                th = line[len(P_THUMB):].strip()
                job["thumb"] = th if th.lower().startswith(("http://", "https://")) else ""
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
                if job["fmt"] == "gif":
                    pct = 55 * frac
                    if status == "finished":
                        pct = max(pct, 55)
                    job["percent"] = max(job["percent"], min(pct, 58.0))
                    job["speed"] = _num(speed)
                    job["eta"] = int(_num(eta))
                    return
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
                if len(f) == 2 and f[1] == "started" and job["fmt"] != "gif":
                    job["status"] = "running"
                    job["speed"] = 0.0
                    job["eta"] = 0
                    job["percent"] = max(job["percent"], 95.0)
