"""ダウンロード用の小さな道具。標準ライブラリだけで動かす。"""
import hashlib
import json
import urllib.request

from .version import __version__

UA = f"OQIDA/{__version__}"


def http_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download_file(url, dest, progress=None, cancel=None, timeout=30):
    """urlをdestに保存。progress(done, total) を呼ぶ。cancel()がTrueなら中断。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    sha = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel and cancel():
                raise InterruptedError("canceled")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return sha.hexdigest()


def parse_version(tag: str):
    """'v1.2.3' や '2026.10.21' を数字のタプルにする。"""
    parts = []
    for p in tag.strip().lstrip("vV").replace("-", ".").split("."):
        if p.isdigit():
            parts.append(int(p))
        else:
            break
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    return a > b
