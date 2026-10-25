/* ブラウザだけで見た目を確認するための偽バックエンド（本番では読み込まれない） */
(function () {
  const qs = new URLSearchParams(location.search);
  const T = (a, b) => "data:image/svg+xml;utf8," + encodeURIComponent("<svg xmlns='http://www.w3.org/2000/svg' width='240' height='136'><rect width='240' height='136' fill='" + a + "'/><rect y='84' width='240' height='52' fill='" + b + "'/><circle cx='176' cy='46' r='18' fill='" + b + "'/></svg>");
  const settings = {
    theme: qs.get("theme") || "dark", accent: qs.get("accent") ? "#" + qs.get("accent") : "#ff8a3d",
    language: qs.get("lang") || "ja", format: qs.get("fmt") || "mp4",
    mp4_quality: "1080", mp3_bitrate: "320", gif_width: "480", gif_fps: "15", cookies_browser: "none", auto_check_app: true, auto_update_ytdlp: true,
    download_dir: "", download_dir_effective: "C:\\Users\\mel\\Downloads\\OQIDA",
    language_effective: (qs.get("lang") || "ja") === "auto" ? "ja" : (qs.get("lang") || "ja"),
  };
  const jobs = qs.get("empty") ? [] : [
    { id: 1, url: "https://youtu.be/aaa", fmt: "mp4", status: "running", site: "youtube.com", thumb: T("#33414d", "#4f6a7d"), title: "【4K】夜の熊本城を歩く Night Walk Kumamoto Castle", percent: 62.4, speed: 6.8 * 1048576, eta: 41, filepath: "", error: "" },
    { id: 2, url: "https://x.com/a/status/1", fmt: "mp4", status: "running", site: "x.com", thumb: T("#3d3a4a", "#6a6580"), title: "新作のティザー映像を公開しました", percent: 97, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 3, url: "https://www.tiktok.com/@u/video/3", fmt: "mp4", status: "queued", site: "tiktok.com", thumb: "", title: "", percent: 0, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 4, url: "https://youtu.be/ddd", fmt: "mp3", status: "done", site: "youtube.com", thumb: T("#4a3a33", "#86604c"), title: "Lo-fi Beats for Studying", percent: 100, speed: 0, eta: 0, filepath: "x", error: "" },
    { id: 7, url: "C:\\Videos\\clip.mp4", kind: "convert", fmt: "gif", status: "running", stage: "convert", site: "", thumb: "", title: "clip", percent: 46, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 8, url: "C:\\Videos\\play.mp4", kind: "convert", fmt: "gif", status: "done", stage: "", site: "", thumb: "", title: "play", percent: 100, speed: 0, eta: 0, filepath: "x", error: "" },
    { id: 6, url: "https://youtu.be/ggg", fmt: "gif", status: "running", stage: "convert", site: "youtube.com", thumb: T("#33414d", "#6a8fa0"), title: "ねこがジャンプする瞬間", percent: 82, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 5, url: "https://www.instagram.com/p/xyz", fmt: "mp4", status: "error", site: "instagram.com", thumb: "", title: "", percent: 12, speed: 0, eta: 0, filepath: "", error: "login" },
  ];
  let upd = qs.get("upd") || "available";
  const setup = qs.get("setup")
    ? { running: true, component: "ffmpeg", done: 86 * 1048576, total: 191 * 1048576, error: "", missing: ["ffmpeg"] }
    : { running: false, component: "", done: 0, total: 0, error: "", missing: [] };
  const state = () => ({
    version: "0.2.0", settings, jobs, setup,
    app_update: { state: upd, current: "0.2.0", latest: "0.3.0", notes: "- yt-dlpの更新処理を改善\n- 設定画面を追加", done: 40e6, total: 100e6, error: "" },
    ytdlp: { state: "uptodate", current: "2026.10.21", latest: "2026.10.21", error: "" },
  });
  const ok = async () => ({ ok: true });
  window.pywebview = { api: {
    get_state: async () => state(), startup: ok, set_setting: async (k, v) => { settings[k] = v; return { ok: true }; },
    add_download: async (u, g) => { window.__addCall = [u, g]; return { ok: true }; }, paste_clipboard: async () => "https://x.com/example/status/1234567890",
    pick_video: async () => ({ ok: true, path: "C:\\Videos\\clip.mp4", name: "clip.mp4", duration: 83 }),
    convert_gif: async (p, g) => { window.__cvCall = [p, g]; return { ok: true }; },
    pick_folder: ok, open_download_dir: ok, open_data_dir: ok, reveal: ok, cancel: ok, remove: ok, retry: ok,
    clear_finished: ok, check_app_update: ok,
    download_app_update: async () => { upd = "downloading"; setTimeout(() => { upd = "ready"; }, 700); return { ok: true }; },
    apply_app_update: async () => { window.__applied = true; return { ok: true }; },
    check_ytdlp: ok, update_ytdlp: ok, retry_setup: ok, reinstall_tool: ok,
  } };
})();
