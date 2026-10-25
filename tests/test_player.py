"""動画プレイヤーで区間を選ぶ画面テスト（本番のMediaServerで動画を配信して確認）"""
import subprocess
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
from core.mediaserver import MediaServer  # noqa: E402

UI = (Path(__file__).resolve().parent.parent / "ui" / "index.html").as_uri()


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    f = tmp_path_factory.mktemp("pl") / "sample.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=8",
                    "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(f)], check=True)
    return str(f)


@pytest.fixture
def served(sample):
    ms = MediaServer()
    url = ms.set_file(sample)
    yield url
    ms.stop()


def open_page(browser, media):
    ctx = browser.new_context(viewport={"width": 1000, "height": 760}, color_scheme="dark")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(UI + f"?mock=1&lang=ja&view=gif&media={media}")
    try:
        pg.click("#updLater", timeout=800)
    except Exception:
        pass
    return pg


def seek(pg, t, sel="#cvVideo"):
    pg.evaluate("""([s,t])=>new Promise(res=>{const v=document.querySelector(s);const h=()=>{v.removeEventListener('seeked',h);res();};v.addEventListener('seeked',h);v.currentTime=t;})""", [sel, t])


def test_player_set_start_end(served):
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        pg = open_page(b, served)
        pg.click("#cvPick")
        pg.wait_for_selector("#cvPlayer:not([hidden])")
        pg.wait_for_function("document.querySelector('#cvVideo').readyState >= 1", timeout=8000)
        assert pg.inner_text("#cvDur") == "0:08"
        seek(pg, 2.5); pg.click("#cvSetStart")
        seek(pg, 6.0); pg.click("#cvSetEnd")
        assert pg.input_value("#cvStart") == "0:02.5"
        assert pg.input_value("#cvEnd") == "0:06" and pg.input_value("#cvLen") == "3.5"
        left = float(pg.eval_on_selector("#cvSel", "e=>parseFloat(e.style.left)"))
        width = float(pg.eval_on_selector("#cvSel", "e=>parseFloat(e.style.width)"))
        assert abs(left - 31.25) < 1 and abs(width - 43.75) < 1       # 2.5〜6秒 / 8秒
        # 数字を直接入れても帯が追従する
        pg.fill("#cvStart", "0:01"); pg.press("#cvStart", "Enter")
        pg.wait_for_timeout(100)
        assert abs(float(pg.eval_on_selector("#cvSel", "e=>parseFloat(e.style.left)")) - 12.5) < 1
        assert pg.errs == []
        b.close()


def test_player_hidden_without_media(served):
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1000, "height": 760})
        pg = ctx.new_page()
        pg.goto(UI + "?mock=1&lang=ja&view=gif")        # media なし
        try: pg.click("#updLater", timeout=800)
        except Exception: pass
        pg.click("#cvPick")
        pg.wait_for_timeout(300)
        assert pg.is_hidden("#cvPlayer")                # 再生URLが無ければプレイヤーは隠れる
        b.close()
