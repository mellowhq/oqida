"""GIF変換。動画の指定した区間を、ffmpegでGIFにする。"""
import os
import re
import subprocess

MIN_LENGTH = 0.5
MAX_LENGTH = 60.0
WIDTHS = (320, 480, 640)
FPS_CHOICES = (10, 15, 20)
_NUM = re.compile(r"\d+(?:\.\d+)?")


def parse_time(text) -> float:
    """'90' / '1:30' / '01:02:03' / '1:30.5' を秒にする。空欄は0。形式が違えば ValueError('bad_time')。"""
    s = str(text if text is not None else "").strip().replace("：", ":")
    if not s:
        return 0.0
    parts = s.split(":")
    if len(parts) > 3 or not all(_NUM.fullmatch(p) for p in parts):
        raise ValueError("bad_time")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def validate(start, length, width, fps) -> dict:
    """画面から来た値を確認して、数値にそろえる。問題があれば ValueError('bad_time' / 'bad_gif')。"""
    st = parse_time(start)
    ln = parse_time(length)
    try:
        w, f = int(width), int(fps)
    except (TypeError, ValueError):
        raise ValueError("bad_gif") from None
    if st < 0 or st > 24 * 3600 or not (MIN_LENGTH <= ln <= MAX_LENGTH) or w not in WIDTHS or f not in FPS_CHOICES:
        raise ValueError("bad_gif")
    return {"start": round(st, 3), "length": round(ln, 3), "width": w, "fps": f}


def section_arg(g) -> str:
    """yt-dlpの --download-sections に渡す値"""
    return f"*{g['start']:g}-{g['start'] + g['length']:g}"


def build_ffmpeg_args(ffmpeg, src, dst, fps, width, trim=None):
    """きれいな色になるよう、動画から色のパレットを作ってからGIFにする（palettegen / paletteuse）。
    trim=(開始秒, 長さ秒) を渡すと、元の動画のその区間だけを使う（パソコン内の動画を変換するとき用）。"""
    vf = (f"fps={fps},scale='min({width},iw)':-1:flags=lanczos,split[s0][s1];"
          "[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5")
    cut = ["-ss", f"{trim[0]:g}", "-t", f"{trim[1]:g}"] if trim else []
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
            *cut, "-i", src, "-an", "-vf", vf, "-loop", "0", dst]


def probe_duration(ffprobe, path, no_window=0):
    """動画の長さ（秒）。調べられなければ None"""
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
                           capture_output=True, text=True, timeout=20, creationflags=no_window)
        v = float(r.stdout.strip().splitlines()[0])
        return v if v > 0 else None
    except Exception:
        return None


def progress_seconds(line):
    """ffmpegの -progress 出力1行から、いま何秒まで進んだかを取り出す。該当しなければ None。"""
    for key, div in (("out_time_us=", 1e6), ("out_time_ms=", 1e6)):   # ms と書いてあっても実際はマイクロ秒
        if line.startswith(key):
            try:
                return max(0.0, int(line[len(key):]) / div)
            except ValueError:
                return None
    return None


def unique_path(folder, stem, ext):
    """同じ名前があれば「名前 (1).gif」のようにずらす"""
    p = os.path.join(folder, stem + ext)
    n = 1
    while os.path.exists(p):
        p = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return p
