"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

let api = null;
let S = null;            // 最新の状態
let busyPoll = false;
const rows = new Map();  // jobId -> 行の要素
const mq = window.matchMedia("(prefers-color-scheme: dark)");
let pendingAccent = null;   // ユーザーが選んだ直後のアクセント色。保存が確定するまで poll に上書きさせない

const SWATCHES = [
  ["#ff8a3d", "acc_orange"], ["#4c8dff", "acc_blue"], ["#2fd08a", "acc_green"], ["#f0619d", "acc_pink"],
  ["#9b7bff", "acc_purple"], ["#ef5350", "acc_red"], ["#d9d9de", "acc_mono"],
];

/* ---------------- 表示ヘルパー ---------------- */
function fmtBytes(n) {
  if (!n) return "0 MB";
  const mb = n / 1048576;
  return mb >= 1024 ? (mb / 1024).toFixed(2) + " GB" : mb.toFixed(mb < 10 ? 1 : 0) + " MB";
}
function fmtSpeed(bps) { return bps > 0 ? (bps / 1048576).toFixed(1) + " MB/s" : ""; }
function fmtEta(sec) {
  if (!sec || sec < 0) return "";
  const m = Math.floor(sec / 60), s = sec % 60;
  return m + ":" + String(s).padStart(2, "0");
}
let toastTimer = null;
function toast(msg, isErr) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", !!isErr);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 3200);
}

/* ---------------- 色（アクセント） ---------------- */
function hexToRgb(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
function rgbToHex(r, g, b) { return "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join(""); }
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
  let h = 0, s = 0;
  if (mx !== mn) {
    const d = mx - mn;
    s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h /= 6;
  }
  return [h, s, l];
}
function hslToRgb(h, s, l) {
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
  return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
}
function luminance([r, g, b]) {
  const c = [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
/* 選んだ色を、テーマに合わせて読みやすい明るさに調整する */
function adaptAccent(hex, theme) {
  const [h, s, l] = rgbToHsl(...hexToRgb(hex));
  const l2 = theme === "light" ? Math.min(l, 0.4) : Math.max(l, 0.56);
  return hslToRgb(h, s, l2);
}
function applyAccent() {
  const hex = S && S.settings.accent ? S.settings.accent : "#ff8a3d";
  const theme = document.documentElement.dataset.theme;
  const rgb = adaptAccent(hex, theme);
  const [r, g, b] = rgb.map(Math.round);
  const st = document.documentElement.style;
  st.setProperty("--accent", rgbToHex(r, g, b));
  st.setProperty("--accent-ink", luminance(rgb) > 0.38 ? "#111113" : "#ffffff");
  const k = theme === "light" ? 0.7 : 1;
  st.setProperty("--glow", `rgba(${r},${g},${b},${0.55 * k})`);
  st.setProperty("--glow-soft", `rgba(${r},${g},${b},${0.22 * k})`);
  st.setProperty("--glow-faint", `rgba(${r},${g},${b},${0.10 * k})`);
}

/* ---------------- テーマ・言語 ---------------- */
function applyTheme() {
  const th = S ? S.settings.theme : "dark";
  const eff = th === "system" ? (mq.matches ? "dark" : "light") : th;
  document.documentElement.dataset.theme = eff;
  applyAccent();
  // 一番上のウィンドウの枠（タイトルバー）の色を、テーマに合わせる（Windowsのみ・対応環境のみ）
  try { if (api && api.set_titlebar) api.set_titlebar(eff === "dark"); } catch (e) { /* 非対応環境では何もしない */ }
}
function applyLang() {
  const st = S && S.settings;
  let l = st ? st.language : "auto";
  if (l === "auto") l = st && st.language_effective ? st.language_effective : (navigator.language || "").startsWith("ja") ? "ja" : "en";
  setLang(l);
  $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  $$("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
  $$("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  $$(".swatch[data-name]").forEach((el) => (el.title = t(el.dataset.name)));
}
mq.addEventListener("change", applyTheme);

/* ---------------- 画面切り替え ---------------- */
function showView(v) {
  $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === v));
  $$(".view").forEach((s) => s.classList.toggle("is-active", s.id === "view-" + v));
  $("main").scrollTop = 0;
}
$$(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

/* ---------------- 設定の入力部品 ---------------- */
$$("[data-setting]").forEach((el) => {
  el.addEventListener("change", async () => {
    const key = el.dataset.setting;
    const val = el.type === "checkbox" ? el.checked : el.value;
    S.settings[key] = val;
    if (key === "theme") applyTheme();
    if (key === "language") applyLang();
    renderAll();
    await api.set_setting(key, val);
  });
});

function buildSwatches() {
  const box = $("#swatches");
  const custom = $("#customSwatch");
  SWATCHES.forEach(([hex, name]) => {
    const b = document.createElement("button");
    b.className = "swatch"; b.style.setProperty("--c", hex); b.dataset.hex = hex; b.dataset.name = name;
    b.addEventListener("click", () => setAccent(hex));
    box.insertBefore(b, custom);
  });
  const picker = $("#accentPicker");
  // ドラッグ中（input）は画面にだけ反映。離した時（change）に保存する。
  // pendingAccent を立てておくと、保存が終わる前に poll が走っても、選んだ色が消されない。
  picker.addEventListener("input", () => { pendingAccent = picker.value.toLowerCase(); S.settings.accent = pendingAccent; applyAccent(); renderSwatches(); });
  picker.addEventListener("change", () => setAccent(picker.value));
}
async function setAccent(hex) {
  pendingAccent = hex.toLowerCase();
  S.settings.accent = pendingAccent;
  applyAccent(); renderSwatches();
  await api.set_setting("accent", pendingAccent);
}
function renderSwatches() {
  const cur = (S.settings.accent || "").toLowerCase();
  let preset = false;
  $$(".swatch[data-hex]").forEach((b) => {
    const on = b.dataset.hex === cur;
    b.classList.toggle("is-on", on);
    preset = preset || on;
  });
  $("#customSwatch").classList.toggle("is-on", !preset);
  const picker = $("#accentPicker");
  if (document.activeElement !== picker && picker.value !== (cur || "#ff8a3d")) picker.value = cur || "#ff8a3d";
}

function renderSettings() {
  const st = S.settings;
  $$("[data-setting]").forEach((el) => {
    const v = st[el.dataset.setting];
    if (el.type === "checkbox") el.checked = !!v;
    else if (el.value !== String(v)) el.value = String(v);
  });
  const fmt = st.format, isGif = fmt === "gif";
  $("#ctlMp4").hidden = fmt !== "mp4";
  $("#ctlMp3").hidden = !["mp3", "m4a", "opus"].includes(fmt);          // 音質を選べるのは、圧縮する形式だけ（FLAC・WAVはそのまま）
  $("#ctlRangeOn").hidden = isGif;                                       // GIFは区間の指定が必須。それ以外は「区間を指定」をオンにしたときだけ
  const showRange = isGif || $("#rangeOn").checked;
  ["ctlGifStart", "ctlGifEnd", "ctlGifLen"].forEach((id) => ($("#" + id).hidden = !showRange));
  ["ctlGifWidth", "ctlGifFps", "gifNote"].forEach((id) => ($("#" + id).hidden = !isGif));
  $("#ctlThumb").hidden = isGif;
  dlRange.setMax(isGif ? MAX_GIF : MAX_MEDIA);
  const limited = String(st.size_limit_mb) !== "0";
  $("#sizeNote").hidden = !limited;
  $("#cvSizeNote").hidden = !limited;
  $("#tcSizeNote").hidden = !limited;
  // GIF変換ページ: 区間オフなら開始/終了/長さを隠す
  const cvRangeOn = $("#cvRangeOn").checked;
  $$(".cv-range").forEach((el) => (el.hidden = !cvRangeOn));
  // ファイル変換ページ: 区間オンのときだけ表示。音声のロスレス(FLAC/WAV)はサイズ上限の対象外の注意は size_note で足りる
  const tcRangeOn = $("#tcRangeOn").checked;
  $$(".tc-range").forEach((el) => (el.hidden = !tcRangeOn));
  $("#folderPath").textContent = st.download_dir_effective;
  $("#folderPath").title = st.download_dir_effective;
  renderSwatches();
}

/* ---------------- 開始・終了・長さの入力（どれかを変えると残りが連動する） ---------------- */
const MIN_LEN = 0.5, MAX_GIF = 60, MAX_MEDIA = 21600;      // GIFは最長60秒、MP4・音声は最長6時間
function parseTime(str) {
  const s = String(str == null ? "" : str).trim().replace(/：/g, ":");
  if (!s) return 0;
  const parts = s.split(":");
  if (parts.length > 3 || !parts.every((p) => /^\d+(\.\d+)?$/.test(p))) return NaN;
  return parts.reduce((a, p) => a * 60 + parseFloat(p), 0);
}
function fmtTime(sec) {
  const r = Math.round(sec * 10) / 10;
  const h = Math.floor(r / 3600), m = Math.floor((r % 3600) / 60), x = r % 60;
  const xs = Number.isInteger(x) ? String(x).padStart(2, "0") : x.toFixed(1).padStart(4, "0");
  return h ? h + ":" + String(m).padStart(2, "0") + ":" + xs : m + ":" + xs;
}
const fmtLen = (sec) => String(Math.round(sec * 10) / 10);
function makeRange(startId, endId, lenId, getDuration) {
  const el = { s: $("#" + startId), e: $("#" + endId), l: $("#" + lenId) };
  const v = { start: 0, len: 10 };
  let max = MAX_GIF;
  const dur = () => { const d = getDuration(); return d && d > 0 ? d : null; };
  let onShow = null;
  const show = () => {
    el.s.value = fmtTime(v.start); el.e.value = fmtTime(v.start + v.len); el.l.value = fmtLen(v.len);
    if (onShow) onShow();
  };
  // 動画の長さ・最長60秒・最短0.5秒に収まるよう、開始と長さを整える
  const fit = () => {
    const d = dur();
    if (d) v.start = Math.min(v.start, Math.max(0, d - MIN_LEN));
    v.len = Math.min(max, Math.max(MIN_LEN, v.len));
    if (d && v.start + v.len > d) v.len = Math.max(MIN_LEN, d - v.start);
    if (d && v.start + v.len > d + 1e-6) v.start = Math.max(0, d - v.len);
  };
  el.s.addEventListener("change", () => {
    const x = parseTime(el.s.value);
    if (Number.isNaN(x)) { toast(t("e_bad_time"), true); show(); return; }
    v.start = x; fit(); show();
  });
  el.l.addEventListener("change", () => {
    const x = parseTime(el.l.value);
    if (Number.isNaN(x)) { toast(t("e_bad_gif"), true); show(); return; }
    if (x > max) toast(t(max === MAX_GIF ? "e_len_max" : "e_len_max_media"), true);
    v.len = x; fit(); show();
  });
  el.e.addEventListener("change", () => {
    let x = parseTime(el.e.value);
    if (Number.isNaN(x)) { toast(t("e_bad_time"), true); show(); return; }
    const d = dur();
    if (d) x = Math.min(x, d);
    if (x < v.start + MIN_LEN) { toast(t("e_bad_range"), true); show(); return; }
    if (x - v.start > max) toast(t(max === MAX_GIF ? "e_len_max" : "e_len_max_media"), true);
    v.len = x - v.start; fit(); show();
  });
  [el.s, el.e, el.l].forEach((i) => i.addEventListener("keydown", (ev) => { if (ev.key === "Enter") i.blur(); }));
  show();
  return {
    // 送る値（秒の数字）
    value: () => ({ start: String(Math.round(v.start * 1000) / 1000), length: String(Math.round(v.len * 1000) / 1000) }),
    reset: () => { v.start = 0; v.len = 10; fit(); show(); },
    setMax: (m) => { if (m === max) return; max = m; fit(); show(); },
    get: () => ({ start: v.start, len: v.len }),
    setStart: (sec) => { v.start = Math.max(0, sec); fit(); show(); },
    setEnd: (sec) => { if (sec > v.start + MIN_LEN) { v.len = sec - v.start; fit(); show(); } },
    onChange: (fn) => { onShow = fn; },
  };
}

/* ---------------- 動画を見ながら区間を選ぶプレイヤー ---------------- */
function bindPlayer(prefix, range, getFile) {
  const video = $("#" + prefix + "Video");
  const track = $("#" + prefix + "Track");
  const sel = $("#" + prefix + "Sel"), cur = $("#" + prefix + "Cur");
  const playBtn = $("#" + prefix + "Play");
  let dur = 0;
  const pct = (sec) => (dur ? Math.max(0, Math.min(100, (sec / dur) * 100)) : 0);
  function paintRange() {
    const r = range.get();
    sel.style.left = pct(r.start) + "%";
    sel.style.width = Math.max(0, pct(r.start + r.len) - pct(r.start)) + "%";
  }
  function paintCursor() {
    cur.style.left = pct(video.currentTime) + "%";
    $("#" + prefix + "Now").textContent = durText(video.currentTime);
  }
  video.addEventListener("loadedmetadata", () => {
    dur = video.duration || 0;
    $("#" + prefix + "Dur").textContent = durText(dur);
    paintRange(); paintCursor();
  });
  video.addEventListener("timeupdate", paintCursor);
  video.addEventListener("play", () => (playBtn.textContent = "❚❚"));
  video.addEventListener("pause", () => (playBtn.textContent = "▶"));
  playBtn.addEventListener("click", () => { if (video.paused) video.play(); else video.pause(); });
  // トラックをクリック/ドラッグで頭出し
  let scrubbing = false;
  const seekAt = (e) => {
    const rect = track.getBoundingClientRect();
    const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (dur) video.currentTime = p * dur;
  };
  track.addEventListener("pointerdown", (e) => { scrubbing = true; track.setPointerCapture(e.pointerId); seekAt(e); });
  track.addEventListener("pointermove", (e) => { if (scrubbing) seekAt(e); });
  track.addEventListener("pointerup", () => { scrubbing = false; });
  $("#" + prefix + "SetStart").addEventListener("click", () => { range.setStart(video.currentTime); paintRange(); });
  $("#" + prefix + "SetEnd").addEventListener("click", () => { range.setEnd(video.currentTime); paintRange(); });
  $("#" + prefix + "PlaySel").addEventListener("click", () => {
    const r = range.get();
    video.currentTime = r.start; video.play();
    const stop = () => { if (video.currentTime >= r.start + r.len) { video.pause(); video.removeEventListener("timeupdate", stop); } };
    video.addEventListener("timeupdate", stop);
  });
  return {
    // ファイルを読み込む（なければプレイヤーを隠す）
    load: (info) => {
      const el = $("#" + prefix + "Player");
      if (info && info.media) { video.src = info.media; el.hidden = false; }
      else { video.removeAttribute("src"); video.load && video.load(); el.hidden = true; }
    },
    // 数字入力が変わったら選択範囲を塗り直す
    refresh: paintRange,
  };
}
let cvFile = null;   // GIF変換で選んだファイル { path, name, duration }
const dlRange = makeRange("gifStart", "gifEnd", "gifLen", () => null);
const cvRange = makeRange("cvStart", "cvEnd", "cvLen", () => (cvFile && cvFile.duration) || null);
let tcFile = null;   // ファイル変換で選んだファイル
const tcRange = makeRange("tcStart", "tcEnd", "tcLen", () => (tcFile && tcFile.duration) || null);
tcRange.setMax(MAX_MEDIA);
const cvPlayer = bindPlayer("cv", cvRange, () => cvFile);
const tcPlayer = bindPlayer("tc", tcRange, () => tcFile);
cvRange.onChange(() => cvPlayer.refresh());
tcRange.onChange(() => tcPlayer.refresh());

/* ---------------- ダウンロード操作 ---------------- */
let pendingDup = null;   // 「もう一度ダウンロード」を選ばれたときのために覚えておく
async function startDownload(force = false) {
  const input = $("#urlInput");
  const url = input.value.trim();
  if (!url) { toast(t("e_bad_url"), true); input.focus(); return; }
  const rng = S.settings.format === "gif" || $("#rangeOn").checked ? dlRange.value() : null;
  const r = await api.add_download(url, rng, force === true);
  if (r.ok) { input.value = ""; clearPreview(); await poll(); }
  else if (r.error === "duplicate") {
    pendingDup = { url, rng };
    $("#dupMsg").textContent = t("dup_msg", { t: r.title || url });
    $("#dupDialog").hidden = false;
  } else toast(t("e_" + (r.error || "bad_url")), true);
}
$("#startBtn").addEventListener("click", () => startDownload());
$("#rangeOn").addEventListener("change", () => renderSettings());
$("#dupCancel").addEventListener("click", () => { $("#dupDialog").hidden = true; pendingDup = null; });
$("#dupAgain").addEventListener("click", async () => {
  $("#dupDialog").hidden = true;
  if (!pendingDup) return;
  const { url, rng } = pendingDup; pendingDup = null;
  const r = await api.add_download(url, rng, true);
  if (r.ok) { $("#urlInput").value = ""; await poll(); } else toast(t("e_" + (r.error || "bad_url")), true);
});
$("#urlInput").addEventListener("keydown", (e) => { if (e.key === "Enter") startDownload(); });
$("#pasteBtn").addEventListener("click", async () => {
  const txt = await api.paste_clipboard();
  if (txt) { $("#urlInput").value = txt.split(/\s+/)[0]; schedulePreview(); }
  $("#urlInput").focus();
});

/* ---------------- ダウンロード前のプレビュー ---------------- */
const URL_RE = /^https?:\/\/\S+$/i;
let pvTimer = null, pvSeq = 0, pvForUrl = "";
function clearPreview() {
  pvForUrl = "";
  $("#previewCard").hidden = true;
  $("#pvLoading").hidden = true;
}
function durText(sec) {
  if (!sec && sec !== 0) return "";
  const s = Math.round(sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(r).padStart(2, "0");
}
function schedulePreview() {
  const url = $("#urlInput").value.trim();
  clearTimeout(pvTimer);
  if (!URL_RE.test(url)) { clearPreview(); return; }
  if (url === pvForUrl) return;                    // 同じURLは取り直さない
  pvTimer = setTimeout(() => loadPreview(url), 500);
}
async function loadPreview(url) {
  const seq = ++pvSeq;
  pvForUrl = url;
  $("#previewCard").hidden = true;
  $("#pvLoading").hidden = false;
  let info;
  try { info = await api.preview_url(url); } catch (e) { info = { ok: false }; }
  if (seq !== pvSeq || $("#urlInput").value.trim() !== url) return;   // 入力が変わっていたら無視
  $("#pvLoading").hidden = true;
  if (!info || !info.ok) { clearPreview(); applyQualityOptions(null); return; }  // 失敗時は静かに閉じる（DLは試せる）
  if (info.playlist) {
    $("#pvThumb").parentElement.style.display = "none";
    $("#pvTitle").textContent = info.title || url;
    $("#pvMeta").textContent = "";
    $("#pvPlaylist").hidden = false;
    $("#pvPlaylist").textContent = t("pv_playlist", { n: info.count || "?" });
    applyQualityOptions(null);
  } else {
    $("#pvThumb").parentElement.style.display = info.thumbnail ? "" : "none";
    if (info.thumbnail) $("#pvThumb").src = info.thumbnail;
    $("#pvTitle").textContent = info.title || url;
    const bits = [];
    if (info.uploader) bits.push(info.uploader);
    if (info.duration) bits.push(durText(info.duration));
    if (info.live) bits.push(t("pv_live"));
    else if (info.max_height) bits.push(t("pv_max", { h: info.max_height }));
    $("#pvMeta").textContent = bits.join("  ·  ");
    $("#pvPlaylist").hidden = true;
    applyQualityOptions(info.quality_options);
  }
  $("#previewCard").hidden = false;
}
// プレビューで分かった画質だけを、画質ドロップダウンに出す（最高画質は常に先頭）
function applyQualityOptions(heights) {
  const sel = $("[data-setting=mp4_quality]");
  if (!sel) return;
  const cur = S.settings.mp4_quality;
  if (!heights || !heights.length) {
    sel.innerHTML = '<option value="best">' + t("q_best") + "</option>" +
      [1080, 720, 480].map((h) => `<option value="${h}">${h}p</option>`).join("");
  } else {
    sel.innerHTML = '<option value="best">' + t("q_best") + "</option>" +
      heights.map((h) => `<option value="${h}">${h}p</option>`).join("");
  }
  // 以前選んでいた画質が一覧になければ「最高画質」に寄せる
  sel.value = [...sel.options].some((o) => o.value === String(cur)) ? String(cur) : "best";
  if (sel.value !== String(cur)) { S.settings.mp4_quality = sel.value; api.set_setting("mp4_quality", sel.value); }
}
$("#pvClose").addEventListener("click", () => { clearPreview(); });
$("#urlInput").addEventListener("input", schedulePreview);
$("#folderChange").addEventListener("click", async () => { await api.pick_folder(); await poll(); });
$("#folderOpen").addEventListener("click", () => api.open_download_dir());
$("#clearBtn").addEventListener("click", async () => { await api.clear_finished(); await poll(); });
$("#dataDirBtn").addEventListener("click", () => api.open_data_dir());

/* ---------------- 一覧（ダウンロードとGIF変換で、それぞれ別の一覧に出す） ---------------- */
function makeRow(job) {
  const el = document.createElement("div");
  el.className = "job";
  el.innerHTML = '<div class="thumb"><img alt="" referrerpolicy="no-referrer"><span class="fmt"></span></div>' +
    '<div class="info"><div class="title"></div>' +
    '<div class="meta"><span class="site"></span><span class="state"></span><span class="num speed"></span><span class="num eta"></span><span class="num size"></span><span class="fit"></span></div>' +
    '<div class="bar"><i></i></div></div><div class="acts"></div>';
  const img = $("img", el);
  img.addEventListener("error", () => (img.hidden = true));
  el.dataset.id = job.id;
  return el;
}
function setActions(el, job) {
  const acts = $(".acts", el);
  acts.textContent = "";
  const add = (label, fn) => {
    const b = document.createElement("button");
    b.className = "link"; b.textContent = label; b.addEventListener("click", fn);
    acts.appendChild(b);
  };
  const id = job.id;
  const after = async (p) => { await p; await poll(); };
  // 一時停止できるのは、ダウンロード中のもの（変換や仕上げの最中は不可）
  if (job.status === "running" && job.kind !== "convert" && job.stage !== "convert" && job.percent < 95) add(t("act_pause"), () => after(api.pause(id)));
  if (job.status === "paused") add(t("act_resume"), () => after(api.resume(id)));
  if (["queued", "running", "paused"].includes(job.status)) add(t("act_cancel"), () => after(api.cancel(id)));
  if (job.status === "error") add(t("act_detail"), () => openLog(id));
  if (job.status === "done") add(t("act_reveal"), () => api.reveal(id));
  if (job.status === "error" || job.status === "canceled") add(t("act_retry"), () => after(api.retry(id)));
  if (job.status !== "running") add(t("act_remove"), () => after(api.remove(id)));
  el.dataset.acted = [job.status, job.stage || "", job.percent >= 95 ? 1 : 0, LANG].join("|");
}
function updateRow(el, job) {
  const converting = job.status === "running" && (job.stage === "convert" || job.percent >= 95);
  el.dataset.status = job.status;
  $(".fmt", el).textContent = job.fmt.toUpperCase();
  const img = $("img", el);
  if (job.thumb && img.dataset.src !== job.thumb) { img.dataset.src = job.thumb; img.hidden = false; img.src = job.thumb; }
  if (!job.thumb) img.hidden = true;
  $(".title", el).textContent = job.title || job.url;
  $(".title", el).title = job.title || job.url;
  $(".site", el).textContent = job.site || "";
  let state = t("st_" + (converting ? "converting" : job.status));
  if (job.status === "error") state = t("e_" + (job.error || "unknown"));
  $(".state", el).textContent = state;
  const live = job.status === "running" && !converting;
  $(".speed", el).textContent = live ? fmtSpeed(job.speed) : "";
  $(".eta", el).textContent = live ? fmtEta(job.eta) : "";
  $(".size", el).textContent = job.status === "done" && job.size ? (job.size / 1e6).toFixed(1) + " MB" : "";
  $(".fit", el).textContent = job.status === "done" && job.fitted ? t("fitted") : "";
  const bar = $(".bar", el);
  $("i", bar).style.width = job.percent.toFixed(1) + "%";
  bar.classList.toggle("busy", converting || job.status === "queued");
  if (el.dataset.acted !== [job.status, job.stage || "", job.percent >= 95 ? 1 : 0, LANG].join("|")) setActions(el, job);
}
function syncList(container, jobs, seen) {
  jobs.forEach((job, idx) => {
    seen.add(job.id);
    let el = rows.get(job.id);
    if (!el) { el = makeRow(job); rows.set(job.id, el); }
    if (container.children[idx] !== el) container.insertBefore(el, container.children[idx] || null);
    updateRow(el, job);
  });
}
const isDone = (j) => !["queued", "running"].includes(j.status);
function renderJobs() {
  const dl = S.jobs.filter((j) => j.kind !== "convert" && j.kind !== "transcode");
  const cv = S.jobs.filter((j) => j.kind === "convert");       // GIF変換
  const tc = S.jobs.filter((j) => j.kind === "transcode");     // ファイル変換
  const seen = new Set();
  syncList($("#queue"), dl, seen);
  syncList($("#cvQueue"), cv, seen);
  syncList($("#tcQueue"), tc, seen);
  for (const [id, el] of rows) if (!seen.has(id)) { el.remove(); rows.delete(id); }
  $("#clearBtn").hidden = !dl.some(isDone);
  $("#emptyBox").hidden = dl.length > 0;
  $("#dlHead").hidden = dl.length === 0;
  $("#queueLabel").textContent = t("queue") + (dl.length ? " (" + dl.length + ")" : "");
  $("#cvClear").hidden = !cv.some(isDone);
  $("#cvHead").hidden = cv.length === 0;
  $("#cvLabel").textContent = t("cv_list") + (cv.length ? " (" + cv.length + ")" : "");
  $("#tcClear").hidden = !tc.some(isDone);
  $("#tcHead").hidden = tc.length === 0;
  $("#tcLabel").textContent = t("tc_list") + (tc.length ? " (" + tc.length + ")" : "");
}

/* ---------------- GIF変換（パソコン内の動画） ---------------- */
function fmtDur(sec) {
  const s = Math.round(sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(r).padStart(2, "0");
}
function setCvFile(info) {
  if (!info || !info.ok) { if (info && info.error && info.error !== "canceled") toast(t("e_" + (info.error === "bad_file" ? "bad_file" : "drop_na")), true); return; }
  cvFile = info;
  cvRange.reset();
  cvPlayer.load(info);
  $("#cvFileName").textContent = info.name;
  $("#cvFileName").title = info.path;
  $("#cvFileMeta").textContent = info.duration ? t("cv_len", { d: fmtDur(info.duration) }) : "";
  $("#cvDrop").classList.add("has-file");
  $("#cvGo").disabled = false;
}
$("#cvPick").addEventListener("click", async () => setCvFile(await api.pick_video()));
$("#cvRangeOn").addEventListener("change", () => renderSettings());
$("#cvGo").addEventListener("click", async () => {
  if (!cvFile) { toast(t("cv_pick_first"), true); return; }
  const g = $("#cvRangeOn").checked ? cvRange.value() : { whole: true };   // 区間オフ = 動画まるごと
  const r = await api.convert_gif(cvFile.path, g);
  if (r.ok) await poll(); else toast(t("e_" + (r.error || "convert")), true);
});
$("#cvClear").addEventListener("click", async () => { await api.clear_finished(); await poll(); });

/* ---------------- ファイル変換（パソコン内の動画/音声 → 別の形式） ---------------- */
function setTcFile(info) {
  if (!info || !info.ok) { if (info && info.error && info.error !== "canceled") toast(t("e_" + (info.error === "bad_file" ? "bad_file" : "drop_na")), true); return; }
  tcFile = info;
  tcRange.reset();
  tcPlayer.load(info);
  $("#tcFileName").textContent = info.name;
  $("#tcFileName").title = info.path;
  $("#tcFileMeta").textContent = info.duration ? t("cv_len", { d: fmtDur(info.duration) }) : "";
  $("#tcDrop").classList.add("has-file");
  $("#tcGo").disabled = false;
}
$("#tcPick").addEventListener("click", async () => setTcFile(await api.pick_video()));
$("#tcRangeOn").addEventListener("change", () => renderSettings());
$("#tcGo").addEventListener("click", async () => {
  if (!tcFile) { toast(t("cv_pick_first"), true); return; }
  const rng = $("#tcRangeOn").checked ? tcRange.value() : null;
  const r = await api.convert_file(tcFile.path, S.settings.conv_format, rng);
  if (r.ok) await poll(); else toast(t("e_" + (r.error || "convert")), true);
});
$("#tcClear").addEventListener("click", async () => { await api.clear_finished(); await poll(); });
const tdz = $("#tcDrop");
tdz.addEventListener("dragenter", () => tdz.classList.add("over"));
tdz.addEventListener("dragleave", () => tdz.classList.remove("over"));
tdz.addEventListener("drop", () => tdz.classList.remove("over"));
// 動画ファイルをウィンドウに落としたとき、ブラウザが勝手にそのファイルを開かないようにする。
// 実際のファイルの場所は、アプリ本体(Python)側が受け取って window.onFileDropped で知らせる。
["dragover", "drop"].forEach((ev) => window.addEventListener(ev, (e) => e.preventDefault()));
const dz = $("#cvDrop");
dz.addEventListener("dragenter", () => dz.classList.add("over"));
dz.addEventListener("dragleave", () => dz.classList.remove("over"));
dz.addEventListener("drop", () => dz.classList.remove("over"));
window.onFileDropped = (info) => {
  const view = $(".nav-item.is-active") && $(".nav-item.is-active").dataset.view;
  if (view === "conv") setTcFile(info);
  else { showView("gif"); setCvFile(info); }
};

/* ---------------- 初回セットアップ ---------------- */
const PART_NAMES = { ytdlp: "yt-dlp", ffmpeg: "ffmpeg", deno: "Deno" };
function renderSetup() {
  const su = S.setup;
  const need = su.missing.length > 0;
  $("#setup").hidden = !need;
  $("#startBtn").disabled = need;
  if (!need) return;
  const comp = su.component || su.missing[0];
  $("#setupPart").textContent = PART_NAMES[comp] || comp;
  const pct = su.total ? Math.min(100, (su.done / su.total) * 100) : 0;
  $("#setupBar").style.width = pct.toFixed(1) + "%";
  $("#setupNum").textContent = su.total ? fmtBytes(su.done) + " / " + fmtBytes(su.total) : "";
  const hasErr = !su.running && !!su.error;
  $("#setupErr").hidden = !hasErr;
  $("#setupErr").textContent = hasErr ? t("setup_fail") + ": " + su.error : "";
  $("#setupRetry").hidden = !hasErr;
}
$("#setupRetry").addEventListener("click", () => api.retry_setup());

/* ---------------- 設定: アップデート・部品 ---------------- */
function renderUpdates() {
  const a = S.app_update;
  $("#appVer").textContent = "v" + S.version;
  let txt = "", btn = "b_check", dis = false, bar = false, notes = "";
  switch (a.state) {
    case "idle": txt = t("u_idle"); break;
    case "checking": txt = t("u_checking"); btn = "b_checking"; dis = true; break;
    case "uptodate": txt = t("u_uptodate"); break;
    case "available": txt = t("u_available", { v: a.latest }); btn = "b_download"; notes = a.notes; break;
    case "downloading": {
      const p = a.total ? Math.floor((a.done / a.total) * 100) : 0;
      txt = t("u_downloading", { p }); btn = "b_wait"; dis = true; bar = true;
      $("#appUpdBar i").style.width = p + "%"; break;
    }
    case "ready": txt = t("u_ready"); btn = "b_apply"; break;
    case "installing": txt = t("u_installing"); btn = "b_wait"; dis = true; break;
    case "error": txt = a.error === "dev_mode" ? t("u_dev") : t("u_error"); break;
  }
  const el = $("#appUpdText");
  el.textContent = txt;
  el.className = "row-sub" + (a.state === "available" || a.state === "ready" ? " ok" : a.state === "error" ? " bad" : "");
  $("#appUpdBar").hidden = !bar;
  $("#appUpdNotes").hidden = !notes;
  $("#appUpdNotes").textContent = notes;
  const b = $("#appUpdBtn");
  b.textContent = t(btn); b.disabled = dis; b.dataset.mode = a.state;

  const y = S.ytdlp;
  $("#ytVer").textContent = y.current || "";
  let ytxt = "", ybtn = "b_check", ydis = false;
  switch (y.state) {
    case "idle": ytxt = y.current ? t("u_idle") : t("not_installed"); break;
    case "checking": ytxt = t("u_checking"); ybtn = "b_checking"; ydis = true; break;
    case "uptodate": ytxt = t("u_uptodate"); break;
    case "available": ytxt = t("u_available", { v: y.latest }); ybtn = "b_update"; break;
    case "waiting": ytxt = t("u_waiting"); ybtn = "b_wait"; ydis = true; break;
    case "updating": ytxt = t("u_updating"); ybtn = "b_wait"; ydis = true; break;
    case "updated": ytxt = t("u_updated"); break;
    case "skipped": ytxt = t("u_skipped", { v: y.skip || y.latest }); ybtn = "b_update_anyway"; break;
    case "error": ytxt = t("u_error"); break;
  }
  const ye = $("#ytUpdText");
  ye.textContent = ytxt;
  ye.className = "row-sub" + (y.state === "available" ? " ok" : y.state === "error" ? " bad" : "");
  const yb = $("#ytUpdBtn");
  yb.textContent = t(ybtn); yb.disabled = ydis; yb.dataset.mode = y.state;

  // 旧バージョンに戻す（更新したyt-dlpが壊れていたとき用）
  const prev = y.previous;
  const onOlder = !!(prev && y.current && verNewer(prev, y.current));       // 「前の版」のほうが新しい = いま旧バージョンを使っている
  $("#ytBackText").textContent = !prev ? t("s_ytdlp_back_none") : onOlder && y.skip ? t("s_ytdlp_back_skip", { v: prev }) : t("s_ytdlp_back_has", { v: prev });
  const bb = $("#ytBackBtn");
  bb.textContent = onOlder ? t("b_forward", { v: prev }) : t("b_back");
  bb.disabled = !prev || ["updating", "waiting", "checking"].includes(y.state);

  $("#navDot").hidden = !["available", "downloading", "ready"].includes(a.state);
  $("#navDot").title = t("nav_update");
  $("#verLabel").textContent = "v" + S.version;
}
/* ---------------- 起動時のアップデート確認 ---------------- */
let updPrompted = false;   // この起動中に聞いたか
let updAccepted = false;   // 「更新する」を選んだか
let updApplying = false;
function renderUpdDialog() {
  const a = S.app_update;
  const dlg = $("#updDialog");
  // 最初のセットアップ中は聞かない。終わってから聞く。
  if (!updPrompted && !updAccepted && a.state === "available" && S.setup.missing.length === 0) {
    updPrompted = true;
    dlg.hidden = false;
  }
  if (dlg.hidden || !updAccepted) return;
  const prog = $("#updProg");
  if (a.state === "downloading") {
    const p = a.total ? Math.floor((a.done / a.total) * 100) : 0;
    $("#updMsg").textContent = t("upd_downloading", { p });
    prog.hidden = false; $("i", prog).style.width = p + "%";
  } else if (a.state === "ready" && !updApplying) {
    updApplying = true;
    $("#updMsg").textContent = t("upd_restarting");
    api.apply_app_update().then((r) => {
      if (r && r.error === "busy") { toast(t("u_busy"), true); dlg.hidden = true; updApplying = false; }
    });
  } else if (a.state === "error") {
    $("#updMsg").textContent = a.error === "dev_mode" ? t("u_dev") : t("u_error");
    prog.hidden = true;
    $("#updNow").hidden = true; $("#updLater").hidden = false; $("#updLater").disabled = false;
  }
}
$("#updLater").addEventListener("click", () => { $("#updDialog").hidden = true; });
$("#updNow").addEventListener("click", async () => {
  updAccepted = true;
  $("#updNow").hidden = true; $("#updLater").disabled = true;
  $("#updMsg").textContent = t("upd_downloading", { p: 0 });
  await api.download_app_update();
  await poll();
});

$("#appUpdBtn").addEventListener("click", async () => {
  const m = $("#appUpdBtn").dataset.mode;
  if (m === "available") await api.download_app_update();
  else if (m === "ready") {
    const r = await api.apply_app_update();
    if (r && r.error === "busy") toast(t("u_busy"), true);
  } else await api.check_app_update();
  await poll();
});
function verNewer(a, b) {   // "2026.10.30" のような版の新旧
  const pa = String(a).match(/\d+/g) || [], pb = String(b).match(/\d+/g) || [];
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = +(pa[i] || 0), y = +(pb[i] || 0);
    if (x !== y) return x > y;
  }
  return false;
}
$("#ytBackBtn").addEventListener("click", async () => {
  const r = await api.rollback_ytdlp();
  if (r.ok) toast(t("back_done", { v: r.current || "?" }));
  else toast(t(r.error === "busy" ? "u_busy" : "e_ytdlp_back_fail"), true);
  await poll();
});
$("#clearHistoryBtn").addEventListener("click", async () => { await api.clear_history(); await poll(); toast(t("history_cleared")); });

/* ---------------- 失敗の詳細ログ ---------------- */
async function openLog(id) {
  const text = await api.get_job_log(id);
  $("#logText").textContent = text || "-";
  $("#logDialog").hidden = false;
}
function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.cssText = "position:fixed;opacity:0;left:-1000px";
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}
$("#logClose").addEventListener("click", () => { $("#logDialog").hidden = true; });
$("#logCopy").addEventListener("click", async () => {
  const text = $("#logText").textContent;
  let ok = false;
  try { const r = await api.copy_text(text); ok = !!(r && r.ok); } catch (e) { ok = false; }
  if (!ok) ok = fallbackCopy(text);
  toast(ok ? t("log_copied") : t("e_copy_fail"), !ok);
});
$("#ytUpdBtn").addEventListener("click", async () => {
  const m = $("#ytUpdBtn").dataset.mode;
  if (m === "available" || m === "skipped") await api.update_ytdlp();
  else await api.check_ytdlp();
  await poll();
});

function renderParts() {
  const box = $("#parts");
  const miss = new Set(S.setup.missing);
  Object.keys(PART_NAMES).forEach((k) => {
    let row = $("#part-" + k);
    if (!row) {
      row = document.createElement("div");
      row.className = "row"; row.id = "part-" + k;
      row.innerHTML = '<div class="row-text"><div class="row-title"><span class="part-dot"></span><span class="nm"></span></div></div><button class="btn"></button>';
      $("button", row).addEventListener("click", async () => { await api.reinstall_tool(k); await poll(); });
      box.appendChild(row);
    }
    $(".nm", row).textContent = PART_NAMES[k];
    $(".part-dot", row).classList.toggle("ok", !miss.has(k));
    $("button", row).textContent = t("reinstall");
    $("button", row).disabled = S.setup.running;
  });
}

/* ---------------- 全体 ---------------- */
function renderAll() {
  renderSettings(); renderJobs(); renderSetup(); renderUpdates(); renderParts(); renderUpdDialog();
}
async function poll() {
  if (busyPoll) return;
  busyPoll = true;
  try {
    const prevLang = S && S.settings.language_effective;
    const prevAccent = S && S.settings.accent;
    S = await api.get_state();
    if (pendingAccent) {
      if (S.settings.accent === pendingAccent) pendingAccent = null;   // アプリ側が追いついた
      else S.settings.accent = pendingAccent;                          // まだなら、選んだ色を保つ
    }
    if (S.settings.language_effective !== prevLang) applyLang();
    applyTheme();
    renderAll();
  } catch (e) { /* 通信失敗時は次の周期で再試行 */ }
  busyPoll = false;
}

async function init() {
  api = window.pywebview.api;
  S = await api.get_state();
  buildSwatches();
  const qs = new URLSearchParams(location.search);
  if (qs.get("view")) showView(qs.get("view"));
  applyTheme(); applyLang(); renderAll();
  api.startup();
  setInterval(poll, 500);
  $("#urlInput").focus();
}

if (new URLSearchParams(location.search).get("mock")) {
  const s = document.createElement("script");
  s.src = "mock.js";
  s.onload = init;
  document.head.appendChild(s);
} else {
  window.addEventListener("pywebviewready", init);
}
