"""ファイルサイズの上限に収めるための計算。ここは「どう調整するか」を決めるだけで、実行はdownloader側。

1MB = 1,000,000バイトで数える（1MiBより小さいので、どちらの数え方でも上限を超えない）。
計算どおりに仕上がらないことがあるので、少し余裕（SAFETY）を見て、できたあとに必ず実際の大きさを測る。
"""
import math

MB = 1_000_000
SAFETY = 0.94                 # 上限の94%を狙う（コンテナやメタデータの分の余裕）
MP3_LADDER = (320, 256, 224, 192, 160, 128, 112, 96, 80, 64, 56, 48, 40, 32)
MIN_GIF_WIDTH = 80
MAX_GIF_ATTEMPTS = 7


def limit_bytes(mb) -> int:
    """設定値(MB)をバイトにする。0・空・不正は「上限なし」(0)"""
    try:
        v = float(mb)
    except (TypeError, ValueError):
        return 0
    return int(v * MB) if v > 0 else 0


def mp3_bitrate_for(duration, limit, wanted_kbps):
    """上限に収まる一番高い音質(kbps)。wanted_kbps より上げることはしない。32kbpsでも収まらなければ None"""
    if not duration or duration <= 0 or limit <= 0:
        return None
    fit = limit * SAFETY * 8 / duration / 1000
    for b in MP3_LADDER:
        if b <= wanted_kbps and b <= fit:
            return b
    return None


def video_plan(duration, limit, src_height=None):
    """MP4を上限に収めるための、映像・音声のビットレートと高さの目安。収まる見込みがなければ None"""
    if not duration or duration <= 0 or limit <= 0:
        return None
    total = limit * SAFETY * 8 / duration / 1000          # 映像+音声で使える kbps
    audio = 128 if total >= 600 else 96 if total >= 300 else 64 if total >= 150 else 48
    video = total - audio
    if video < 60:
        return None
    height = (1080 if video >= 3500 else 720 if video >= 1800 else 480 if video >= 800
              else 360 if video >= 400 else 240 if video >= 180 else 144)
    if src_height:
        height = min(height, int(src_height))
    return {"v_kbps": int(video), "a_kbps": audio, "height": height}


def retry_video_plan(plan, size, limit):
    """できあがりが上限を超えたとき、実際の大きさに合わせて映像のビットレートを下げ直す"""
    v = int(plan["v_kbps"] * (limit * SAFETY / size) * 0.97)
    if v < 60:
        return None
    return dict(plan, v_kbps=v)


def next_gif_params(cur, actual_width, size, limit, attempt):
    """GIFが上限を超えたとき、次に試す設定。これ以上縮められなければ None
    cur: {"width","fps","colors"} / actual_width: できたGIFの実際の幅 / attempt: いま失敗した試行の番号(1始まり)"""
    if size <= 0 or limit <= 0 or attempt >= MAX_GIF_ATTEMPTS or actual_width <= MIN_GIF_WIDTH:
        return None
    ratio = limit * SAFETY / size                         # 1より小さい。面積(幅の2乗)にほぼ比例すると見て縮める
    new = dict(cur)
    new["width"] = max(MIN_GIF_WIDTH, int(actual_width * math.sqrt(ratio) * 0.95))
    if attempt >= 2:
        new["colors"] = min(cur["colors"], 128)
        new["fps"] = min(cur["fps"], 12)
    if attempt >= 3:
        new["colors"] = min(cur["colors"], 64)
        new["fps"] = min(cur["fps"], 10)
    if attempt >= 4:
        new["fps"] = min(cur["fps"], 8)
    return new
