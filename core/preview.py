"""ダウンロード前のプレビュー。yt-dlp -J（情報だけ取得）のJSONを、画面で使う形に整える。"""

STD_HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160)


def parse_info(info: dict) -> dict:
    """yt-dlp -J の出力（1本ぶん）を、プレビュー用の辞書にする。"""
    if not isinstance(info, dict):
        return {"ok": False}
    if info.get("_type") == "playlist" or "entries" in info:
        n = len(info.get("entries") or [])
        return {"ok": True, "playlist": True, "count": n, "title": info.get("title") or "",
                "uploader": info.get("uploader") or info.get("channel") or ""}
    heights = sorted({f.get("height") for f in (info.get("formats") or []) if f.get("height")}, reverse=True)
    if not heights and info.get("height"):
        heights = [info["height"]]
    has_video = bool(heights) or any((f.get("vcodec") or "none") != "none" for f in (info.get("formats") or []))
    dur = info.get("duration")
    return {
        "ok": True, "playlist": False,
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id") or "",
        "duration": float(dur) if isinstance(dur, (int, float)) else None,
        "thumbnail": _thumb(info),
        "heights": heights,
        "max_height": heights[0] if heights else None,
        "has_video": has_video,
        "live": bool(info.get("is_live")),
    }


def _thumb(info):
    t = info.get("thumbnail")
    if isinstance(t, str) and t.startswith(("http://", "https://")):
        return t
    thumbs = info.get("thumbnails") or []
    best = None
    for th in thumbs:
        u = th.get("url") if isinstance(th, dict) else None
        if isinstance(u, str) and u.startswith(("http://", "https://")):
            best = u
    return best or ""


def quality_options(max_height):
    """プレビューで分かった最大画質までの、選べる画質の一覧（高い順）。"""
    if not max_height:
        return list(STD_HEIGHTS[::-1])
    return [h for h in STD_HEIGHTS if h <= max_height][::-1]
