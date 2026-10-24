"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

let api = null;
let S = null;            // 最新の状態
let view = "main";
let busyPoll = false;
const rows = new Map();  // jobId -> 行の要素
const mq = window.matchMedia("(prefers-color-scheme: dark)");

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

/* ---------------- テーマ・言語 ---------------- */
function applyTheme() {
  const th = S ? S.settings.theme : "dark";
  const eff = th === "system" ? (mq.matches ? "dark" : "light") : th;
  document.documentElement.dataset.theme = eff;
}
function applyLang() {
  const st = S && S.settings;
  let l = st ? st.language : "auto";
  if (l === "auto") l = st && st.language_effective ? st.language_effective : (navigator.language || "").startsWith("ja") ? "ja" : "en";
  setLang(l);
  $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  $$("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
}
mq.addEventListener("change", applyTheme);

/* ---------------- 画面切り替え ---------------- */
function showView(v) {
  view = v;
  $$(".tab").forEach((b) => b.classList.toggle("is-active", b.dataset.view === v));
  $$(".view").forEach((s) => s.classList.toggle("is-active", s.id === "view-" + v));
  $("main").scrollTop = 0;
}
$$(".tab").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
$("#updateBannerBtn").addEventListener("click", () => {
  showView("settings");
  $("#grpUpdate").scrollIntoView({ block: "start" });
});

/* ---------------- 設定のセグメント ---------------- */
$$(".seg[data-setting]").forEach((seg) => {
  seg.addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const key = seg.dataset.setting;
    const val = seg.dataset.bool ? btn.dataset.value === "true" : btn.dataset.value;
    S.settings[key] = val;
    renderSettings();
    if (key === "theme") applyTheme();
    if (key === "language") { applyLang(); renderAll(); }
    await api.set_setting(key, val);
  });
});
function renderSettings() {
  const st = S.settings;
  $$(".seg[data-setting]").forEach((seg) => {
    const cur = String(st[seg.dataset.setting]);
    $$("button", seg).forEach((b) => b.classList.toggle("is-on", b.dataset.value === cur));
  });
  $("#ctlMp4").hidden = st.format !== "mp4";
  $("#ctlMp3").hidden = st.format !== "mp3";
  $("#folderPath").textContent = st.download_dir_effective;
  $("#folderPath").title = st.download_dir_effective;
}

/* ---------------- ダウンロード操作 ---------------- */
async function startDownload() {
  const input = $("#urlInput");
  const url = input.value.trim();
  if (!url) { toast(t("e_bad_url"), true); input.focus(); return; }
  const r = await api.add_download(url);
  if (r.ok) { input.value = ""; await poll(); }
  else toast(t("e_" + (r.error || "bad_url")), true);
}
$("#startBtn").addEventListener("click", startDownload);
$("#urlInput").addEventListener("keydown", (e) => { if (e.key === "Enter") startDownload(); });
$("#pasteBtn").addEventListener("click", async () => {
  const txt = await api.paste_clipboard();
  if (txt) { $("#urlInput").value = txt.split(/\s+/)[0]; }
  $("#urlInput").focus();
});
$("#folderChange").addEventListener("click", async () => { await api.pick_folder(); await poll(); });
$("#folderOpen").addEventListener("click", () => api.open_download_dir());
$("#clearBtn").addEventListener("click", async () => { await api.clear_finished(); await poll(); });
$("#dataDirBtn").addEventListener("click", () => api.open_data_dir());

/* ---------------- キュー ---------------- */
function makeRow(job) {
  const el = document.createElement("div");
  el.className = "job";
  el.innerHTML = '<div class="tag"></div><div class="title"></div><div class="acts"></div>' +
    '<div class="meta"><span class="state"></span><span class="mono speed"></span><span class="mono eta"></span></div>' +
    '<div class="bar"><i></i></div>';
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
  if (job.status === "queued" || job.status === "running") add(t("act_cancel"), () => after(api.cancel(id)));
  if (job.status === "done") add(t("act_reveal"), () => api.reveal(id));
  if (job.status === "error" || job.status === "canceled") add(t("act_retry"), () => after(api.retry(id)));
  if (job.status !== "running") add(t("act_remove"), () => after(api.remove(id)));
  el.dataset.acted = job.status + "|" + LANG;
}
function renderJobs() {
  const jobs = S.jobs;
  const q = $("#queue");
  const seen = new Set();
  jobs.forEach((job, idx) => {
    seen.add(job.id);
    let el = rows.get(job.id);
    if (!el) { el = makeRow(job); rows.set(job.id, el); }
    if (q.children[idx] !== el) q.insertBefore(el, q.children[idx] || null);
    const converting = job.status === "running" && job.percent >= 95;
    el.dataset.status = job.status;
    $(".tag", el).textContent = job.fmt.toUpperCase();
    $(".title", el).textContent = job.title || job.url;
    $(".title", el).title = job.title || job.url;
    let state = t("st_" + (converting ? "converting" : job.status));
    if (job.status === "error") state = t("e_" + (job.error || "unknown"));
    $(".state", el).textContent = state;
    $(".speed", el).textContent = job.status === "running" && !converting ? fmtSpeed(job.speed) : "";
    $(".eta", el).textContent = job.status === "running" && !converting ? fmtEta(job.eta) : "";
    const bar = $(".bar", el);
    $("i", bar).style.width = job.percent.toFixed(1) + "%";
    bar.classList.toggle("busy", converting || job.status === "queued");
    if (el.dataset.acted !== job.status + "|" + LANG) setActions(el, job);
  });
  for (const [id, el] of rows) if (!seen.has(id)) { el.remove(); rows.delete(id); }
  const doneCount = jobs.filter((j) => !["queued", "running"].includes(j.status)).length;
  $("#clearBtn").hidden = doneCount === 0;
  $("#emptyBox").hidden = jobs.length > 0;
  $("#queueLabel").textContent = t("queue") + (jobs.length ? "  " + jobs.length : "");
}

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
    case "error": ytxt = t("u_error"); break;
  }
  const ye = $("#ytUpdText");
  ye.textContent = ytxt;
  ye.className = "row-sub" + (y.state === "available" ? " ok" : y.state === "error" ? " bad" : "");
  const yb = $("#ytUpdBtn");
  yb.textContent = t(ybtn); yb.disabled = ydis; yb.dataset.mode = y.state;

  // バナー
  const show = ["available", "downloading", "ready"].includes(a.state);
  $("#updateBanner").hidden = !show;
  if (show) $("#updateBannerText").textContent = t("banner_text", { v: a.latest });
  $("#verLabel").textContent = "v" + S.version;
}
$("#appUpdBtn").addEventListener("click", async () => {
  const m = $("#appUpdBtn").dataset.mode;
  if (m === "available") await api.download_app_update();
  else if (m === "ready") {
    const r = await api.apply_app_update();
    if (r && r.error === "busy") toast(t("u_busy"), true);
  } else await api.check_app_update();
  await poll();
});
$("#ytUpdBtn").addEventListener("click", async () => {
  const m = $("#ytUpdBtn").dataset.mode;
  if (m === "available") await api.update_ytdlp();
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
  renderSettings(); renderJobs(); renderSetup(); renderUpdates(); renderParts();
}
async function poll() {
  if (busyPoll) return;
  busyPoll = true;
  try {
    const prevLang = S && S.settings.language_effective;
    S = await api.get_state();
    if (S.settings.language_effective !== prevLang) applyLang();
    applyTheme();
    renderAll();
  } catch (e) { /* 通信失敗時は次の周期で再試行 */ }
  busyPoll = false;
}

async function init() {
  api = window.pywebview.api;
  S = await api.get_state();
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
