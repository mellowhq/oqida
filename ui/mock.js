/* ブラウザだけで見た目を確認するための偽バックエンド（本番では読み込まれない） */
(function () {
  const qs = new URLSearchParams(location.search);
  const T = (a, b) => "data:image/svg+xml;utf8," + encodeURIComponent("<svg xmlns='http://www.w3.org/2000/svg' width='240' height='136'><rect width='240' height='136' fill='" + a + "'/><rect y='84' width='240' height='52' fill='" + b + "'/><circle cx='176' cy='46' r='18' fill='" + b + "'/></svg>");
  const settings = {
    theme: qs.get("theme") || "dark", accent: qs.get("accent") ? "#" + qs.get("accent") : "#ff8a3d",
    language: qs.get("lang") || "ja", format: qs.get("fmt") || "mp4",
    mp4_quality: "1080", mp3_bitrate: "320", gif_width: "480", gif_fps: "15", conv_format: "mp4", size_limit_mb: qs.get("limit") || "0",
    max_parallel: "1", speed_limit: "0", save_thumb: false, history_keep: true, ytdlp_skip: qs.get("back") ? "2026.10.30" : "",
    cookies_browser: "none", auto_check_app: true, auto_update_ytdlp: true,
    download_dir: "", download_dir_effective: "C:\\Users\\mel\\Downloads\\OQIDA",
    language_effective: (qs.get("lang") || "ja") === "auto" ? "ja" : (qs.get("lang") || "ja"),
  };
  let jobs = qs.get("empty") ? [] : [
    { id: 1, url: "https://youtu.be/aaa", fmt: "mp4", status: "running", site: "youtube.com", thumb: T("#33414d", "#4f6a7d"), title: "【4K】夜の熊本城を歩く Night Walk Kumamoto Castle", percent: 62.4, speed: 6.8 * 1048576, eta: 41, filepath: "", error: "" },
    { id: 9, url: "https://youtu.be/hhh", fmt: "m4a", status: "paused", site: "youtube.com", thumb: T("#3a4a3d", "#5f8068"), title: "作業用BGM 3時間ミックス", percent: 38, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 2, url: "https://x.com/a/status/1", fmt: "mp4", status: "running", site: "x.com", thumb: T("#3d3a4a", "#6a6580"), title: "新作のティザー映像を公開しました", percent: 97, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 3, url: "https://www.tiktok.com/@u/video/3", fmt: "mp4", status: "queued", site: "tiktok.com", thumb: "", title: "", percent: 0, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 4, url: "https://youtu.be/ddd", fmt: "mp3", status: "done", site: "youtube.com", thumb: T("#4a3a33", "#86604c"), title: "Lo-fi Beats for Studying", percent: 100, speed: 0, eta: 0, filepath: "x", error: "", size: 9400000, fitted: true },
    { id: 7, url: "C:\\Videos\\clip.mp4", kind: "convert", fmt: "gif", status: "running", stage: "convert", site: "", thumb: "", title: "clip", percent: 46, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 8, url: "C:\\Videos\\play.mp4", kind: "convert", fmt: "gif", status: "done", stage: "", site: "", thumb: "", title: "play", percent: 100, speed: 0, eta: 0, filepath: "x", error: "", size: 7800000, fitted: false },
    { id: 10, url: "C:\\Videos\\talk.mov", kind: "transcode", fmt: "mp3", status: "running", stage: "convert", site: "", thumb: "", title: "talk", percent: 54, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 11, url: "C:\\Videos\\clip.mkv", kind: "transcode", fmt: "mp4", status: "done", stage: "", site: "", thumb: "", title: "clip", percent: 100, speed: 0, eta: 0, filepath: "x", error: "", size: 18200000, fitted: true },
    { id: 6, url: "https://youtu.be/ggg", fmt: "gif", status: "running", stage: "convert", site: "youtube.com", thumb: T("#33414d", "#6a8fa0"), title: "ねこがジャンプする瞬間", percent: 82, speed: 0, eta: 0, filepath: "", error: "" },
    { id: 5, url: "https://www.instagram.com/p/xyz", fmt: "mp4", status: "error", site: "instagram.com", thumb: "", title: "", percent: 12, speed: 0, eta: 0, filepath: "", error: "login" },
  ];
  jobs.forEach((j) => { j.kind = j.kind || "download"; j.stage = j.stage || ""; });
  let upd = qs.get("upd") || "available";
  const setup = qs.get("setup")
    ? { running: true, component: "ffmpeg", done: 86 * 1048576, total: 191 * 1048576, error: "", missing: ["ffmpeg"] }
    : { running: false, component: "", done: 0, total: 0, error: "", missing: [] };
  // yt-dlp: ふだんは「更新前の版」が残っている状態。?back=1 は、旧バージョンに戻している状態
  let yt = qs.get("back")
    ? { state: "skipped", current: "2026.10.01", latest: "2026.10.30", previous: "2026.10.30" }
    : { state: "uptodate", current: "2026.10.30", latest: "2026.10.30", previous: qs.get("noprev") ? null : "2026.10.01" };
  const state = () => ({
    version: "0.5.0", settings, jobs, setup,
    app_update: { state: upd, current: "0.5.0", latest: "0.6.0", notes: "- yt-dlpの更新処理を改善\n- 設定画面を追加", done: 40e6, total: 100e6, error: "" },
    ytdlp: { state: yt.state, current: yt.current, latest: yt.latest, error: "", previous: yt.previous, skip: settings.ytdlp_skip },
  });
  const ok = async () => ({ ok: true });
  const find = (id) => jobs.find((j) => j.id === id);
  window.pywebview = { api: {
    get_state: async () => state(), startup: ok, set_setting: async (k, v) => { settings[k] = v; return { ok: true }; },
    add_download: async (u, g, f) => {
      window.__addCall = [u, g, !!f];
      if (qs.get("dup") && !f) return { ok: false, error: "duplicate", title: "Lo-fi Beats for Studying" };
      return { ok: true };
    },
    paste_clipboard: async () => "https://x.com/example/status/1234567890",
    pick_video: async () => ({ ok: true, path: "C:\\Videos\\clip.mp4", name: "clip.mp4", duration: 83, media: (new URLSearchParams(location.search)).get("media") || "" }),
    convert_gif: async (p, g) => { window.__cvCall = [p, g]; return { ok: true }; },
    convert_file: async (p, f, r) => { window.__tcCall = [p, f, r]; return { ok: true }; },
    preview_url: async (u) => {
      if (/playlist|list=/.test(u)) return { ok: true, playlist: true, count: 23, title: "作業用BGMまとめ" };
      return { ok: true, playlist: false, title: "【4K】夜の熊本城を歩く Night Walk Kumamoto Castle",
        uploader: "Mellow Walks", duration: 752, thumbnail: T("#33414d", "#4f6a7d"),
        heights: [2160, 1440, 1080, 720, 480], max_height: 2160, has_video: true, live: false,
        quality_options: [2160, 1440, 1080, 720, 480] };
    },
    pick_folder: ok, open_download_dir: ok, open_data_dir: ok, reveal: ok,
    cancel: async (id) => { const j = find(id); if (j) j.status = "canceled"; return { ok: true }; },
    remove: async (id) => { jobs = jobs.filter((j) => j.id !== id); return { ok: true }; },
    retry: ok, clear_finished: ok,
    pause: async (id) => { const j = find(id); if (j) { j.status = "paused"; j.speed = 0; j.eta = 0; } window.__paused = id; return { ok: true }; },
    resume: async (id) => { const j = find(id); if (j) j.status = "running"; window.__resumed = id; return { ok: true }; },
    get_job_log: async (id) => "OQIDA 0.5.0 / yt-dlp 2026.10.30 / nt win32\nsite: instagram.com / format: mp4 / status: error / error: login\nurl: https://www.instagram.com/p/xyz\n\n$ ~\\AppData\\Local\\OQIDA\\bin\\yt-dlp.exe --no-playlist -f bv*+ba/b https://www.instagram.com/p/xyz\nERROR: [Instagram] xyz: Requested content is not available, rate-limit reached or login required\n[OQIDA] failed: login",
    copy_text: async (text) => { window.__copied = text; return { ok: true }; },
    clear_history: async () => { jobs = jobs.filter((j) => !["done", "error", "canceled"].includes(j.status)); return { ok: true }; },
    check_app_update: ok,
    download_app_update: async () => { upd = "downloading"; setTimeout(() => { upd = "ready"; }, 700); return { ok: true }; },
    apply_app_update: async () => { window.__applied = true; return { ok: true }; },
    check_ytdlp: ok,
    update_ytdlp: async () => { settings.ytdlp_skip = ""; window.__ytUpdated = true; return { ok: true }; },
    rollback_ytdlp: async () => {
      if (!yt.previous) return { ok: false, error: "no_previous" };
      const before = yt.current;
      yt = { state: yt.state, current: yt.previous, latest: yt.latest, previous: before };
      const older = yt.current < before;      // 版の数字は、文字として比べても新旧が分かる形式
      settings.ytdlp_skip = older ? before : "";
      yt.state = older ? "skipped" : "uptodate";
      window.__rolledBack = [yt.current, before];
      return { ok: true, current: yt.current, previous: before };
    },
    retry_setup: ok, reinstall_tool: ok, set_titlebar: ok,
  } };
})();
