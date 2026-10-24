"""画面の動きをブラウザで確認（モックのバックエンド使用）。"""
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
UI = (Path(__file__).resolve().parent.parent / "ui" / "index.html").as_uri()


@pytest.fixture
def page():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 940, "height": 700}, color_scheme="dark")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(UI + "?mock=1&lang=ja&theme=dark")
        pg.wait_for_timeout(600)
        yield pg
        assert errs == []
        b.close()


def test_theme_switch(page):
    page.click(".tab[data-view=settings]")
    page.click('.seg[data-setting=theme] button[data-value=light]')
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.click('.seg[data-setting=theme] button[data-value=system]')
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"   # color_scheme=dark
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.dataset.theme") == "light"


def test_language_switch(page):
    assert page.inner_text(".tab[data-view=main]") == "ダウンロード"
    page.click(".tab[data-view=settings]")
    page.click('.seg[data-setting=language] button[data-value=en]')
    page.wait_for_timeout(200)
    assert page.inner_text(".tab[data-view=main]") == "Download"
    assert page.get_attribute("#urlInput", "placeholder").startswith("https://")
    assert "Version 0.2.0" in page.inner_text("#appUpdText")


def test_format_switch_shows_right_options(page):
    assert page.is_visible("#ctlMp4") and not page.is_visible("#ctlMp3")
    page.click('.seg[data-setting=format] button[data-value=mp3]')
    page.wait_for_timeout(100)
    assert page.is_visible("#ctlMp3") and not page.is_visible("#ctlMp4")


def test_empty_url_shows_toast(page):
    page.click("#startBtn")
    assert page.is_visible("#toast")
    assert "URL" in page.inner_text("#toast")


def test_update_banner_and_button(page):
    assert page.is_visible("#updateBanner")
    page.click("#updateBannerBtn")
    assert page.evaluate("document.querySelector('#view-settings').classList.contains('is-active')")
    assert page.inner_text("#appUpdBtn") == "ダウンロード"


def test_job_title_is_not_html(page):
    # 動画タイトルにHTMLが入っていても、文字として表示されること
    page.evaluate("""() => { window.pywebview.api.get_state = async () => ({
        version:'0.1.0', settings:{theme:'dark',language:'ja',format:'mp4',mp4_quality:'best',mp3_bitrate:'320',cookies_browser:'none',auto_check_app:true,auto_update_ytdlp:true,download_dir_effective:'C:\\\\x',language_effective:'ja'},
        jobs:[{id:1,url:'u',fmt:'mp4',status:'done',title:'<img src=x onerror=window.__pwned=1>',percent:100,speed:0,eta:0,filepath:'x',error:''}],
        setup:{running:false,missing:[],component:'',done:0,total:0,error:''},
        app_update:{state:'idle',current:'0.1.0',latest:'',notes:'',done:0,total:0,error:''},
        ytdlp:{state:'idle',current:'1',latest:'',error:''}}); }""")
    page.wait_for_timeout(1200)
    assert page.evaluate("window.__pwned") is None
    assert "<img" in page.inner_text(".job .title")
