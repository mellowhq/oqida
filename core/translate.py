"""字幕テキストの翻訳。

仕組みはこの1ファイルにまとめてあり、あとで別の翻訳方法に差し替えやすいようにしてある。
最初の実装は、無料で使える Google 翻訳の非公式エンドポイント。1行ずつではなく、ある程度まとめて
送ることで、文脈が切れて不自然になりにくくする（まとめて送って行数が合わないときだけ1行ずつに切り替える）。
"""
import json
import urllib.parse
import urllib.request

from .netutil import UA

GOOGLE = "https://translate.googleapis.com/translate_a/single"
# OQIDA内部の言語コード → Google翻訳のコード（ほとんど同じ。中国語だけ別名）
_GOOGLE_LANG = {"zh": "zh-CN"}


def _google_code(code):
    return _GOOGLE_LANG.get(code, code)


def _google_once(text, target, source):
    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": "auto" if source == "auto" else _google_code(source),
        "tl": _google_code(target),
        "dt": "t",
        "q": text,
    })
    req = urllib.request.Request(GOOGLE + "?" + params, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    parts = data[0] or []                                   # 文のかけらの配列。つなげると全文になる
    return "".join(seg[0] for seg in parts if seg and seg[0] is not None)


def _google_batch(lines, target, source):
    """複数行をまとめて翻訳する。改行で区切って送り、返ってきた全文を改行で割り戻す。
    行数が合わなければ崩れないよう1行ずつ訳し直す。"""
    joined = "\n".join(lines)
    out = _google_once(joined, target, source)
    res = out.split("\n")
    if len(res) == len(lines):
        return [s.strip() for s in res]
    return [_google_once(ln, target, source) if ln.strip() else ln for ln in lines]


# 翻訳方法の一覧。ここに別の方法を足して backend 名で選べるようにする
BACKENDS = {"google": _google_batch}


def translate_lines(lines, target, source="auto", backend="google", batch_size=20,
                    progress=None, cancel=None):
    """文字列のリストを、設定した言語に翻訳して返す（入力と同じ行数で返る）。
    progress(done, total) を呼び、cancel() が True になったら中断する。"""
    fn = BACKENDS.get(backend)
    if fn is None:
        raise ValueError(f"unknown backend: {backend}")
    if not lines:
        return []
    out, i, n = [], 0, len(lines)
    while i < n:
        if cancel and cancel():
            raise InterruptedError("canceled")
        chunk = lines[i:i + batch_size]
        try:
            out.extend(fn(chunk, target, source))
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"translate failed: {e}") from e
        i += batch_size
        if progress:
            progress(min(i, n), n)
    return out
