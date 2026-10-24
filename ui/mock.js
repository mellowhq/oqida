/* ブラウザだけで見た目を確認するための偽バックエンド（本番では読み込まれない） */
(function () {
  const qs = new URLSearchParams(location.search);
  const settings = {
    theme: qs.get("theme") || "dark", language: qs.get("lang") || "ja", format: qs.get("fmt") || "mp4",
    mp4_quality: "1080", mp3_bitrate: "320", cookies_browser: "none", auto_check_app: true, auto_update_ytdlp: true,
    download_dir: "", download_dir_effective: "C:\\Users\\mel\\Downloads\\OQIDA",
    language_effective: (qs.get("lang") || "ja") === "auto" ? "ja" : (qs.get("lang") || "ja"),
  };
  const jobs = qs.get("empty") ? [] : [
    { id: 1, url: "https://youtu.be/aaa", fmt: "mp4", status: "running", title: "【4K】夜の熊本城を歩く Night Walk Kumamoto Castle", percent: 62.4, speed: 6.8 * 1048576, eta: 41, filepath: "", error: "" },
    { id: 2, url: "https://youtu.be/bbb", fmt: "mp3", status: "running", title: "Lo-fi Beats for Studying", percent: 97, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 3, url: "https://youtu.be/ccc", fmt: "mp4", status: "queued", title: "", percent: 0, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 4, url: "https://youtu.be/ddd", fmt: "mp4", status: "done", title: "ミニマルなデスク環境 2026", percent: 100, speed: 0, eta: 0, filepath: "x", error: "" },
    { id: 5, url: "https://youtu.be/eee", fmt: "mp3", status: "error", title: "Private upload", percent: 12, speed: 0, eta: 0, filepath: "", error: "private" },
  ];
  const upd = qs.get("upd") || "available";
  const setup = qs.get("setup")
    ? { running: true, component: "ffmpeg", done: 86 * 1048576, total: 191 * 1048576, error: "", missing: ["ffmpeg"] }
    : { running: false, component: "", done: 0, total: 0, error: "", missing: [] };
  const state = () => ({
    version: "0.1.0", settings, jobs, setup,
    app_update: { state: upd, current: "0.1.0", latest: "0.2.0", notes: "- yt-dlpの更新処理を改善\n- 設定画面を追加", done: 40e6, total: 100e6, error: "" },
    ytdlp: { state: "uptodate", current: "2026.10.21", latest: "2026.10.21", error: "" },
  });
  const ok = async () => ({ ok: true });
  window.pywebview = { api: {
    get_state: async () => state(), startup: ok, set_setting: async (k, v) => { settings[k] = v; return { ok: true }; },
    add_download: async () => ({ ok: true }), paste_clipboard: async () => "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    pick_folder: ok, open_download_dir: ok, open_data_dir: ok, reveal: ok, cancel: ok, remove: ok, retry: ok,
    clear_finished: ok, check_app_update: ok, download_app_update: ok, apply_app_update: ok,
    check_ytdlp: ok, update_ytdlp: ok, retry_setup: ok, reinstall_tool: ok,
  } };
})();
