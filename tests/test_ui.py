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
    assert "Version 0.6.0" in page.inner_text("#appUpdText")


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


def commit(page, sel, text):
    page.fill(sel, text)
    page.press(sel, "Enter")          # Enterで確定（欄から外れて、連動の計算が動く）


def test_gif_format_shows_its_options_and_sends_range(page):
    page.select_option('[data-setting=format]', "gif")
    for sel in ("#ctlGifStart", "#ctlGifEnd", "#ctlGifLen", "#ctlGifWidth", "#ctlGifFps", "#gifNote", "#ctlSize"):
        assert page.is_visible(sel), sel
    assert not page.is_visible("#ctlMp4") and not page.is_visible("#ctlMp3")
    page.fill("#urlInput", "https://x.com/a/status/1")
    commit(page, "#gifStart", "1:30")
    assert page.input_value("#gifEnd") == "1:40" and page.input_value("#gifLen") == "10"     # 開始を変えると、終了がずれる
    commit(page, "#gifLen", "5")
    assert page.input_value("#gifEnd") == "1:35"                                              # 長さを変えると、終了が変わる
    page.click("#startBtn")
    assert page.evaluate("window.__addCall") == ["https://x.com/a/status/1", {"start": "90", "length": "5"}, False]
    page.select_option('[data-setting=format]', "mp4")
    assert not page.is_visible("#ctlGifStart") and page.is_visible("#ctlMp4") and page.is_visible("#ctlSize")


def test_end_time_sets_the_length(page):
    page.select_option('[data-setting=format]', "gif")
    commit(page, "#gifStart", "0:20")
    commit(page, "#gifEnd", "0:27.5")
    assert page.input_value("#gifLen") == "7.5" and page.input_value("#gifEnd") == "0:27.5"
    commit(page, "#gifEnd", "0:20")                                      # 終了が開始以前 → 元に戻して知らせる
    assert page.is_visible("#toast") and page.input_value("#gifEnd") == "0:27.5"
    commit(page, "#gifStart", "abc")                                     # 形式が違う → 元に戻して知らせる
    assert page.input_value("#gifStart") == "0:20"
    commit(page, "#gifEnd", "5:00")                                      # 60秒を超える → 60秒に収める
    assert page.input_value("#gifLen") == "60" and page.input_value("#gifEnd") == "1:20"


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
    assert (page.input_value("#cvStart"), page.input_value("#cvEnd"), page.input_value("#cvLen")) == ("0:00", "0:10", "10")
    commit(page, "#cvStart", "0:30")
    assert page.input_value("#cvEnd") == "0:40"
    commit(page, "#cvLen", "6")
    assert page.input_value("#cvEnd") == "0:36"
    page.click("#cvGo")
    assert page.evaluate("window.__cvCall") == ["C:\\Videos\\clip.mp4", {"start": "30", "length": "6"}]


def test_gif_range_stays_inside_the_video(page):
    page.click(".nav-item[data-view=gif]")
    page.click("#cvPick")
    page.wait_for_function("document.querySelector('#cvFileName').textContent === 'clip.mp4'")   # 長さ 1:23（83秒）
    commit(page, "#cvStart", "1:20")                                  # 残り3秒しかない → 長さが3秒に縮む
    assert page.input_value("#cvLen") == "3" and page.input_value("#cvEnd") == "1:23"
    commit(page, "#cvStart", "5:00")                                  # 動画の外 → 終わりの手前に収める
    assert page.input_value("#cvStart") == "1:22.5" and page.input_value("#cvEnd") == "1:23"
    commit(page, "#cvStart", "0:10")
    commit(page, "#cvEnd", "9:00")                                    # 終了が動画より後 → 動画の終わりまで（ただし最長60秒）
    assert page.input_value("#cvLen") == "60" and page.input_value("#cvEnd") == "1:10"
    page.click("#cvGo")
    assert page.evaluate("window.__cvCall[1]") == {"start": "10", "length": "60"}


def test_size_limit_select_and_notes(page):
    assert not page.is_visible("#sizeNote")
    page.select_option("#ctlSize select", "10")
    assert page.is_visible("#sizeNote") and "100万バイト" in page.inner_text("#sizeNote")
    page.click(".nav-item[data-view=gif]")
    assert page.input_value("#view-gif select[data-setting=size_limit_mb]") == "10"      # 2つの画面で同じ設定
    assert page.is_visible("#cvSizeNote")
    page.select_option("#view-gif select[data-setting=size_limit_mb]", "0")
    assert not page.is_visible("#cvSizeNote")
    assert page.eval_on_selector_all("#ctlSize option", "els => els.map(e => e.value)") == ["0", "8", "10", "25", "50", "100", "500", "1000"]


def test_finished_rows_show_size_and_fit_note(page):
    rows = page.eval_on_selector_all("#queue .job", """els => els.map(e => ({
        title: e.querySelector('.title').textContent, size: e.querySelector('.size').textContent, fit: e.querySelector('.fit').textContent}))""")
    lofi = next(r for r in rows if r["title"].startswith("Lo-fi"))
    assert lofi["size"] == "9.4 MB" and lofi["fit"] == "上限に合わせて調整"
    assert all(r["size"] == "" for r in rows if r is not lofi)          # 完了していない行にはサイズを出さない
    cv = page.eval_on_selector_all("#cvQueue .job", "els => els.map(e => [e.querySelector('.size').textContent, e.querySelector('.fit').textContent])")
    assert cv == [["", ""], ["7.8 MB", ""]]


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


def test_audio_formats_and_range_switch(page):
    page.select_option('[data-setting=format]', "m4a")
    assert page.is_visible("#ctlMp3")                                   # M4Aは音質を選べる
    assert page.is_visible("#ctlRangeOn") and page.is_visible("#ctlThumb")
    assert not page.is_visible("#ctlGifStart")                          # 区間はオフのときは隠れている
    page.select_option('[data-setting=format]', "flac")
    assert not page.is_visible("#ctlMp3")                               # FLACは音質を選べない（ロスレス）
    page.select_option('[data-setting=format]', "mp4")
    page.check("#rangeOn")
    for sel in ("#ctlGifStart", "#ctlGifEnd", "#ctlGifLen"):
        assert page.is_visible(sel)
    assert not page.is_visible("#ctlGifWidth")                          # 幅・コマ数はGIFだけ
    page.fill("#urlInput", "https://x.com/a/status/1")
    commit(page, "#gifStart", "0:10"); commit(page, "#gifLen", "30")    # MP4は60秒を超えてもよい
    assert page.input_value("#gifLen") == "30"
    page.click("#startBtn")
    assert page.evaluate("window.__addCall") == ["https://x.com/a/status/1", {"start": "10", "length": "30"}, False]


def test_duplicate_dialog(page):
    page.goto(UI + "?mock=1&lang=ja&theme=dark&dup=1")
    page.wait_for_selector("#updDialog:not([hidden])"); page.click("#updLater")
    page.fill("#urlInput", "https://youtu.be/ddd")
    page.click("#startBtn")
    page.wait_for_selector("#dupDialog:not([hidden])")
    assert "Lo-fi Beats for Studying" in page.inner_text("#dupMsg")
    page.click("#dupAgain")
    assert page.evaluate("window.__addCall")[2] is True                 # 「それでも落とす」でforce=True
    assert page.is_hidden("#dupDialog")


def test_pause_resume_actions(page):
    paused_row = page.locator('.job[data-status="paused"]')
    assert paused_row.count() == 1
    assert "一時停止中" in paused_row.locator(".state").inner_text()
    paused_row.locator(".link", has_text="再開").click()
    assert page.evaluate("window.__resumed") == 9
    running = page.locator('#queue .job[data-status="running"]').first    # ダウンロード中には一時停止ボタン
    assert running.locator(".link", has_text="一時停止").count() == 1


def test_error_details_dialog(page):
    err = page.locator('.job[data-status="error"]')
    err.locator(".link", has_text="詳細").click()
    page.wait_for_selector("#logDialog:not([hidden])")
    assert "ERROR" in page.inner_text("#logText") and "login" in page.inner_text("#logText")
    page.click("#logCopy")
    assert "Instagram" in page.evaluate("window.__copied")
    assert page.is_visible("#toast")
    page.click("#logClose")
    assert page.is_hidden("#logDialog")


def test_ytdlp_rollback_available(page):
    page.click(".nav-item[data-view=settings]")
    assert "旧バージョン（2026.10.01）に戻せます" in page.inner_text("#ytBackText")
    assert page.inner_text("#ytBackBtn") == "旧バージョンに戻す"
    page.click("#ytBackBtn")
    assert page.evaluate("window.__rolledBack") == ["2026.10.01", "2026.10.30"]
    page.wait_for_function("document.querySelector('#ytBackText').textContent.includes('自動では入れません')")
    assert "新しい版（2026.10.30）に戻す" == page.inner_text("#ytBackBtn")    # もう一度押すと新しい版へ


def test_ytdlp_rolled_back_shows_skip_and_update_anyway(page):
    page.goto(UI + "?mock=1&lang=ja&theme=dark&back=1&upd=uptodate")
    page.wait_for_timeout(400)
    page.click(".nav-item[data-view=settings]")
    assert "見送っています" in page.inner_text("#ytUpdText")
    assert page.inner_text("#ytUpdBtn") == "それでも更新"
    page.click("#ytUpdBtn")
    assert page.evaluate("window.__ytUpdated") is True


def test_ytdlp_no_previous_version(page):
    page.goto(UI + "?mock=1&lang=ja&theme=dark&noprev=1&upd=uptodate")
    page.wait_for_timeout(400)
    page.click(".nav-item[data-view=settings]")
    assert "まだありません" in page.inner_text("#ytBackText")
    assert page.is_disabled("#ytBackBtn")


def test_speed_limit_and_history_settings(page):
    page.click(".nav-item[data-view=settings]")
    assert page.eval_on_selector_all("select[data-setting=speed_limit] option", "e => e.map(x => x.value)") == ["0", "0.5", "1", "2", "5", "10"]
    page.select_option("select[data-setting=speed_limit]", "2")
    page.click("#clearHistoryBtn")
    assert page.is_visible("#toast") and "履歴を消去" in page.inner_text("#toast")


def test_custom_accent_survives_poll_race(page):
    """カラーピッカーで選んだ色が、保存確定前の poll で元に戻されないこと（報告された不具合）"""
    page.click(".nav-item[data-view=settings]")
    # set_setting をわざと遅延させ、その間に get_state(poll) が先に返る状況を作る
    page.evaluate("""() => {
        const api = window.pywebview.api;
        const realSet = api.set_setting.bind(api);
        api.set_setting = (k, v) => new Promise(res => setTimeout(async () => { await realSet(k, v); res({ok:true}); }, 400));
    }""")
    # input（ドラッグ中）→ change（確定）を発火
    page.evaluate("""() => { const p = document.querySelector('#accentPicker');
        p.value = '#12e0c0'; p.dispatchEvent(new Event('input', {bubbles:true})); p.dispatchEvent(new Event('change', {bubbles:true})); }""")
    accent1 = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    assert accent1 != "" and accent1.lower() != "#ff8a3d"
    page.wait_for_timeout(1300)   # 保存が確定するまでの間に poll が複数回走る
    accent2 = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    assert accent2 == accent1, (accent1, accent2)                     # 元の色に戻っていない
    assert page.evaluate("document.querySelector('#customSwatch').classList.contains('is-on')")
    assert page.evaluate("window.pywebview.api.get_state ? true : true")


def test_titlebar_called_on_theme_change(page):
    page.evaluate("window.__tb = []; const a = window.pywebview.api; const r = a.set_titlebar; a.set_titlebar = (d) => { window.__tb.push(d); return r ? r(d) : {ok:true}; };")
    page.click(".nav-item[data-view=settings]")
    page.select_option("[data-setting=theme]", "light")
    page.wait_for_timeout(100)
    page.select_option("[data-setting=theme]", "dark")
    page.wait_for_timeout(100)
    calls = page.evaluate("window.__tb")
    assert False in calls and True in calls                           # ライト=false / ダーク=true を伝えている
