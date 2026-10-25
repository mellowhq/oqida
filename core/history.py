"""ダウンロード履歴の保存。終わったもの（完了・失敗・中止）だけを history.json に残す。"""
import json
import os

from . import paths

MAX_ENTRIES = 200
FINAL = ("done", "error", "canceled")
KEYS = ("url", "fmt", "kind", "title", "site", "thumb", "filepath", "size", "fitted", "status",
        "error", "error_detail", "quality", "bitrate", "created")


def _file():
    return paths.data_dir() / "history.json"


def _clean(e):
    """壊れたデータや想定外の値が混ざっていても、安全な形にそろえる"""
    if not isinstance(e, dict) or e.get("status") not in FINAL:
        return None
    s = lambda k, d="": e.get(k) if isinstance(e.get(k), str) else d
    n = lambda k: e.get(k) if isinstance(e.get(k), (int, float)) and not isinstance(e.get(k), bool) else 0
    return {
        "url": s("url"), "fmt": s("fmt", "mp4"), "kind": "convert" if e.get("kind") == "convert" else "download",
        "title": s("title"), "site": s("site"),
        "thumb": e.get("thumb") if isinstance(e.get("thumb"), str) and e["thumb"].startswith(("http://", "https://")) else "",
        "filepath": s("filepath"), "size": int(n("size")), "fitted": bool(e.get("fitted")), "status": e["status"],
        "error": s("error"), "error_detail": s("error_detail")[-600:], "quality": s("quality"), "bitrate": s("bitrate"),
        "created": float(n("created")),
    }


def load():
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [c for c in (_clean(e) for e in data) if c][-MAX_ENTRIES:]


def save(entries):
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps([_clean(e) for e in entries if _clean(e)][-MAX_ENTRIES:], ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)


def delete_file():
    try:
        _file().unlink()
    except OSError:
        pass
