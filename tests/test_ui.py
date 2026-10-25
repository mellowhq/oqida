"""画面の動きをブラウザで確認（モックのバックエンド使用）。"""
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
UI = (Path(__file__).resolve().parent.parent / "ui" / "index.html").as_uri()


@pytest.fixture
def browser_only():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1000, "height": 720}, color_scheme="dark")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(UI + "?mock=1&lang=ja&theme=dark")
        pg.wait_for_selector("#updDialog:not([hidden])")
        pg.click("#updLater")
        pg.wait_for_timeout(300)
        yield pg
        assert errs == []
        b.close()


def accent(pg):
    return pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")


def lightness(hex_):
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return (max(r, g, b) + min(r, g, b)) / 2


def test_theme_switch(page):
    page.click(".nav-item[data-view=settings]")
    page.select_option('[data-setting=theme]', "light")
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.select_option('[data-setting=theme]', "system")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"   # color_scheme=dark
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.dataset.theme") == "light"


def test_language_switch(page):
    assert page.inner_text(".nav-item[data-view=main] span") == "ダウンロード"
    page.click(".nav-item[data-view=settings]")
    page.select_option('[data-setting=language]', "en")
    page.wait_for_timeout(200)
    assert page.inner_text(".nav-item[data-view=main] span") == "Download"
    assert page.get_attribute("#urlInput", "placeholder") == "Paste a video URL"
    assert "Version 0.3.0" in page.inner_text("#appUpdText")


def test_format_switch_shows_right_options(page):
    assert page.is_visible("#ctlMp4") and not page.is_visible("#ctlMp3")
    page.select_option('[data-setting=format]', "mp3")
    page.wait_for_timeout(100)
    assert page.is_visible("#ctlMp3") and not page.is_visible("#ctlMp4")


def test_accent_swatch_and_theme_adaptation(page):
    page.click(".nav-item[data-view=settings]")
    before = accent(page)
    page.click('.swatch[data-hex="#4c8dff"]')
    page.wait_for_timeout(150)
    dark_blue = accent(page)
    assert dark_blue != before
    assert page.evaluate("document.querySelector('.swatch[data-hex=\"#4c8dff\"]').classList.contains('is-on')")
    page.select_option('[data-setting=theme]', "light")
    light_blue = accent(page)
    assert lightness(light_blue) <= 0.41 < lightness(dark_blue)   # ライトでは読めるよう暗くなる


def test_custom_accent_color(page):
    page.click(".nav-item[data-view=settings]")
    page.evaluate("""() => { const p = document.querySelector('#accentPicker');
        p.value = '#ff00aa'; p.dispatchEvent(new Event('input', {bubbles:true})); p.dispatchEvent(new Event('change', {bubbles:true})); }""")
    page.wait_for_timeout(150)
    assert page.evaluate("document.querySelector('#customSwatch').classList.contains('is-on')")
    assert accent(page).startswith("#ff")


def test_empty_url_shows_toast(page):
    page.click("#startBtn")
    assert page.is_visible("#toast")
    assert "URL" in page.inner_text("#toast")


def test_update_dot_and_settings(page):
    assert page.is_visible("#navDot")
    page.click(".nav-item[data-view=settings]")
    assert page.evaluate("document.querySelector('#view-settings').classList.contains('is-active')")
    assert page.inner_text("#appUpdBtn") == "ダウンロード"


def test_other_sites_shown(page):
    sites = page.eval_on_selector_all(".job .site", "els => els.map(e => e.textContent)")
    assert "x.com" in sites and "tiktok.com" in sites
    assert "ログイン" in page.inner_text('.job[data-status="error"] .state')


STATE_JS = """(job) => { window.pywebview.api.get_state = async () => ({
    version:'0.2.0', settings:{theme:'dark',accent:'#ff8a3d',language:'ja',format:'mp4',mp4_quality:'best',mp3_bitrate:'320',cookies_browser:'none',auto_check_app:true,auto_update_ytdlp:true,download_dir_effective:'C:\\\\x',language_effective:'ja'},
    jobs:[job],
    setup:{running:false,missing:[],component:'',done:0,total:0,error:''},
    app_update:{state:'idle',current:'0.2.0',latest:'',notes:'',done:0,total:0,error:''},
    ytdlp:{state:'idle',current:'1',latest:'',error:''}}); }"""


def test_job_title_is_not_html(page):
    page.evaluate(STATE_JS, {"id": 1, "url": "u", "fmt": "mp4", "status": "done", "site": "x.com", "thumb": "",
                             "title": "<img src=x onerror=window.__pwned=1>", "percent": 100, "speed": 0, "eta": 0,
                             "filepath": "x", "error": ""})
    page.wait_for_timeout(1200)
    assert page.evaluate("window.__pwned") is None
    assert "<img" in page.inner_text(".job .title")


def test_broken_thumbnail_is_hidden(page):
    page.evaluate(STATE_JS, {"id": 1, "url": "u", "fmt": "mp4", "status": "done", "site": "x.com",
                             "thumb": "http://127.0.0.1:9/none.jpg", "title": "t", "percent": 100, "speed": 0,
                             "eta": 0, "filepath": "x", "error": ""})
    page.wait_for_timeout(1500)
    assert page.evaluate("document.querySelector('.job img').hidden") is True


def test_gif_format_shows_its_options_and_sends_range(page):
    page.select_option('[data-setting=format]', "gif")
    for sel in ("#ctlGifStart", "#ctlGifLen", "#ctlGifWidth", "#ctlGifFps", "#gifNote"):
        assert page.is_visible(sel), sel
    assert not page.is_visible("#ctlMp4") and not page.is_visible("#ctlMp3")
    page.fill("#urlInput", "https://x.com/a/status/1")
    page.fill("#gifStart", "1:30")
    page.fill("#gifLen", "5")
    page.click("#startBtn")
    assert page.evaluate("window.__addCall") == ["https://x.com/a/status/1", {"start": "1:30", "length": "5"}]
    page.select_option('[data-setting=format]', "mp4")
    assert not page.is_visible("#ctlGifStart") and page.is_visible("#ctlMp4")


def test_gif_job_row_is_shown_as_converting(page):
    row = page.locator('#queue .job .fmt', has_text="GIF").locator("xpath=ancestor::div[contains(@class,'job')]")
    assert row.locator(".state").inner_text() == "変換中"


def _fresh(browser, query):
    ctx = browser.new_context(viewport={"width": 1000, "height": 720}, color_scheme="dark")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(UI + query)
    return pg


def test_startup_update_prompt_later(browser_only):
    pg = _fresh(browser_only, "?mock=1&lang=ja&theme=dark")
    pg.wait_for_selector("#updDialog:not([hidden])")
    assert pg.inner_text("#updMsg") == "アップデートがあります。更新しますか？"
    assert pg.inner_text("#updNow") == "更新する" and pg.inner_text("#updLater") == "あとで"
    pg.click("#updLater")
    pg.wait_for_timeout(1300)                       # 何度更新しても、今回の起動中はもう聞かない
    assert not pg.is_visible("#updDialog")
    assert pg.is_visible("#navDot")                 # 目印は残る
    assert pg.errs == []


def test_startup_update_prompt_accept_downloads_and_restarts(browser_only):
    pg = _fresh(browser_only, "?mock=1&lang=ja&theme=dark")
    pg.wait_for_selector("#updDialog:not([hidden])")
    pg.click("#updNow")
    pg.wait_for_function("window.__applied === true", timeout=8000)
    assert pg.inner_text("#updMsg") == "再起動します…"
    assert pg.errs == []


def test_no_prompt_when_up_to_date_or_during_setup(browser_only):
    pg = _fresh(browser_only, "?mock=1&lang=ja&upd=uptodate")
    pg.wait_for_timeout(1200)
    assert not pg.is_visible("#updDialog")
    pg2 = _fresh(browser_only, "?mock=1&lang=ja&setup=1")        # 初回セットアップ中は聞かない
    pg2.wait_for_timeout(1200)
    assert not pg2.is_visible("#updDialog")


def test_gif_convert_screen(page):
    page.click(".nav-item[data-view=gif]")
    assert page.is_visible("#view-gif.is-active") and page.inner_text("h1:visible") == "GIF変換"
    assert page.is_disabled("#cvGo")                                  # ファイルを選ぶまでは押せない
    page.click("#cvPick")
    page.wait_for_function("document.querySelector('#cvFileName').textContent === 'clip.mp4'")
    assert page.inner_text("#cvFileMeta") == "長さ 1:23"
    assert not page.is_disabled("#cvGo")
    page.fill("#cvStart", "0:30"); page.fill("#cvLen", "6")
    page.click("#cvGo")
    assert page.evaluate("window.__cvCall") == ["C:\\Videos\\clip.mp4", {"start": "0:30", "length": "6"}]


def test_gif_convert_list_is_separate_from_downloads(page):
    cv = page.eval_on_selector_all("#cvQueue .job .title", "els => els.map(e => e.textContent)")
    dl = page.eval_on_selector_all("#queue .job .title", "els => els.map(e => e.textContent)")
    assert cv == ["clip", "play"]
    assert "clip" not in dl and "play" not in dl and len(dl) >= 4
    page.click(".nav-item[data-view=gif]")
    states = page.eval_on_selector_all("#cvQueue .job .state", "els => els.map(e => e.textContent)")
    assert states == ["変換中", "完了"]


def test_dropped_file_info_is_shown(page):
    page.click(".nav-item[data-view=main]")
    page.evaluate("window.onFileDropped({ok: true, path: 'D:\\\\a.mov', name: 'a.mov', duration: 3725})")
    assert page.is_visible("#view-gif.is-active")                     # ドロップされたらGIF変換の画面に移る
    assert page.inner_text("#cvFileName") == "a.mov" and page.inner_text("#cvFileMeta") == "長さ 1:02:05"
    page.evaluate("window.onFileDropped({ok: false, error: 'bad_file'})")
    assert page.is_visible("#toast")
    assert page.inner_text("#cvFileName") == "a.mov"                  # 失敗しても選択済みの内容は消さない


def test_dragging_a_file_does_not_navigate_away(page):
    ok = page.evaluate("""() => { const e = new DragEvent('drop', {cancelable: true, bubbles: true}); window.dispatchEvent(e); return e.defaultPrevented; }""")
    assert ok is True
