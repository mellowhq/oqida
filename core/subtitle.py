"""字幕づくりの部品。

・音声を取り出す（ffmpeg）→ 文字起こし（whisper.cpp）→ まとめて翻訳 → .srt を保存、という流れ。
・このファイルは「引数の組み立て」と「.srt の読み書き」だけを受け持ち、実際の実行・進捗・中止は
  downloader 側（Engine）が行う。こうしておくと動かさずにテストしやすい。
"""
import os
import re

# whisper.cpp が扱える言語（よく使うものだけ。auto は自動判定）
SOURCE_LANGS = ("auto", "ja", "en", "ko", "zh", "es", "fr", "de", "pt", "ru", "it")
# 翻訳先に選べる言語
TARGET_LANGS = ("ja", "en", "ko", "zh", "es", "fr", "de", "pt", "ru", "it")

_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)\s*%")
_TS_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


# ---------------------------------------------------------------- 時刻・SRT
def fmt_ts(sec: float) -> str:
    """秒 → 'HH:MM:SS,mmm'（SRTの時刻表記）。"""
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_ts(text: str):
    """'HH:MM:SS,mmm' → 秒。読めなければ None。"""
    m = _TS_RE.search(text)
    if not m:
        return None
    h, mi, s, ms = m.groups()
    ms = (ms + "000")[:3]
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000


def parse_srt(text: str):
    """SRTの文字列 → [{'start': 秒, 'end': 秒, 'text': 本文}] のリスト。"""
    cues = []
    for block in re.split(r"\r?\n\r?\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if not lines:
            continue
        # 先頭が通し番号ならその次が時刻行。番号が無い場合もあるので時刻行を探す
        ti = 0
        if lines[0].strip().isdigit():
            ti = 1
        if ti >= len(lines) or "-->" not in lines[ti]:
            continue
        left, _, right = lines[ti].partition("-->")
        start, end = parse_ts(left), parse_ts(right)
        if start is None or end is None:
            continue
        body = " ".join(s.strip() for s in lines[ti + 1:]).strip()
        cues.append({"start": start, "end": end, "text": body})
    return cues


def build_srt(cues) -> str:
    """cueのリスト → SRTの文字列。"""
    out = []
    for i, c in enumerate(cues, 1):
        out.append(str(i))
        out.append(f"{fmt_ts(c['start'])} --> {fmt_ts(c['end'])}")
        out.append(c["text"])
        out.append("")
    return "\n".join(out).strip() + "\n"


def srt_path_for(video_path: str) -> str:
    """動画と同じフォルダ・同じ名前の .srt のパス（プレイヤーが自動で読み込める形）。"""
    base, _ = os.path.splitext(video_path)
    return base + ".srt"


def parse_progress(line: str):
    """whisper.cpp の進捗行から % を取り出す。無ければ None。"""
    m = _PROGRESS_RE.search(line)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- 実行コマンド
def extract_wav_args(ffmpeg, src, wav):
    """動画/音声から、whisperが読める 16kHz・モノラルのWAVを作るffmpeg引数。"""
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
            "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]


def whisper_args(cli, model, wav, out_base, source_lang="auto", threads=0):
    """whisper-cli に渡す引数。out_base + '.srt' が作られる。
    -sns は「[音楽]」「[拍手]」などの非音声トークンを抑制して、字幕をきれいにする。"""
    a = [cli, "-m", model, "-f", wav, "-osrt", "-of", out_base, "-l", source_lang or "auto",
         "-sns", "--print-progress"]
    if threads and int(threads) > 0:
        a += ["-t", str(int(threads))]
    return a


def _ass_escape(p):
    """ffmpegのsubtitlesフィルタ内でパスを安全に書くためのエスケープ（\\ → /、: → \\:）。"""
    return p.replace("\\", "/").replace(":", "\\:")


def burn_args(ffmpeg, video, srt, out, font="Yu Gothic UI", fontsdir=None):
    """字幕を映像に焼き込むffmpeg引数。
    日本語などを焼き込むとフォントが無くて豆腐(□)になりやすいので、
    日本語を含むフォント(既定: Windows標準の Yu Gothic UI)を指定し、
    フォントの場所(Windowsのフォントフォルダ)も教える。
    注意: パスの特殊文字を避けるため、呼び出し側で srt・出力を単純な名前にしてから渡すこと。"""
    srt_f = _ass_escape(srt)
    style = f"force_style='FontName={font},Outline=1,Shadow=0'"
    inner = f"subtitles='{srt_f}'"
    if fontsdir:
        inner += f":fontsdir='{_ass_escape(fontsdir)}'"
    vf = f"{inner}:{style}"
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
            "-i", video, "-vf", vf, "-c:a", "copy", out]


def collapse_for_translation(cues):
    """翻訳用に、本文がある cue の位置と本文を取り出す（空の cue は翻訳に回さない）。
    返り値: (翻訳する本文リスト, もとのindexリスト)"""
    texts, idx = [], []
    for i, c in enumerate(cues):
        t = " ".join(c["text"].split())
        if t:
            texts.append(t)
            idx.append(i)
    return texts, idx
