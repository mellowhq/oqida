"""main.Api（画面から呼ばれる窓口）の動作確認。pywebview自体は使わない。"""
import json
import time

import main


def test_api_roundtrip(media_server, tmp_path):
    api = main.Api()
    st = api.get_state()
    json.dumps(st)  # 画面へはJSONで渡るので、変換できること
    assert "ytdlp" not in st["setup"]["missing"] and "ffmpeg" not in st["setup"]["missing"]  # テスト環境はPATH上のものを使う
    api.set_setting("download_dir", str(tmp_path / "dl"))
    assert api.set_setting("theme", "bogus") == {"ok": False}
    assert api.add_download("nope") == {"ok": False, "error": "bad_url"}
    r = api.add_download(media_server)
    assert r["ok"]
    for _ in range(100):
        j = api.get_state()["jobs"][0]
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert j["status"] == "done", j
    json.dumps(api.get_state())
    api.clear_finished()
    assert api.get_state()["jobs"] == []
    api._engine.shutdown()
    # 画面から呼べる公開メソッドに、内部オブジェクトが混ざっていないこと
    public = [n for n in dir(api) if not n.startswith("_")]
    assert "startup" in public and "_engine" not in public
