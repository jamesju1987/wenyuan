/* 文渊 前端：原生 JS，无外部依赖 */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ic = (name, cls = "") => `<svg class="i ${cls}"><use href="#i-${name}"/></svg>`;
const content = $("#content");

const S = {
  route: "overview",
  st: null,
  std: null,
  projects: [],
  customers: [],
  lastJobId: null,
  sig: "",
  reviewTab: "pending_review",
  activityFilter: "",
  cols: [],
  colFocus: 0,
  query: "",
};

/* ---------------------------------------------------------------- 基础 */
async function api(path, opts = {}) {
  const o = { ...opts };
  o.headers = { ...(o.headers || {}), "X-Guidang": "1" };   // 服务端只接受带这个标记的改动请求
  if (o.json !== undefined) {
    o.method = o.method || "POST";
    o.headers["Content-Type"] = "application/json";
    o.body = JSON.stringify(o.json);
    delete o.json;
  }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) {
    const msg = (data && (data.detail?.[0]?.msg || data.detail)) || `请求失败（${r.status}）`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function toast(title, body = "", kind = "") {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<img src="/static/icon.svg" alt=""><div><div class="t">${esc(title)}</div>${body ? `<div class="b">${esc(body)}</div>` : ""}</div>`;
  if (kind === "error") el.querySelector(".t").style.color = "var(--red)";
  box.prepend(el);
  while (box.children.length > 4) box.lastChild.remove();
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, kind === "error" ? 6000 : 4200);
}
const fail = (e) => toast("出错了", e.message || String(e), "error");

function toolbar(title, sub = "", actions = "") {
  $("#tb-title").textContent = title;
  $("#tb-sub").textContent = sub;
  $("#tb-actions").innerHTML = actions;
}

function fmtSize(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function fmtTime(s) {
  if (!s) return "";
  const d = typeof s === "number" ? new Date(s * 1000) : new Date(s.replace(" ", "T"));
  const now = new Date();
  const hm = d.toTimeString().slice(0, 5);
  if (d.toDateString() === now.toDateString()) return hm;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `昨天 ${hm}`;
  return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
}
function extOf(name) { const m = /\.([^.]+)$/.exec(name || ""); return m ? m[1].toLowerCase() : ""; }

const DOC_COLORS = {
  doc: ["#2f6fde", "DOC"], docx: ["#2f6fde", "DOC"], rtf: ["#2f6fde", "RTF"], pages: ["#f29d38", "PAGES"],
  xls: ["#1f9d55", "XLS"], xlsx: ["#1f9d55", "XLS"], xlsm: ["#1f9d55", "XLS"], csv: ["#1f9d55", "CSV"],
  ppt: ["#e8622c", "PPT"], pptx: ["#e8622c", "PPT"], key: ["#3b82f6", "KEY"],
  pdf: ["#e5322d", "PDF"], zip: ["#8e8e93", "ZIP"], rar: ["#8e8e93", "RAR"], "7z": ["#8e8e93", "7Z"],
  png: ["#a050dc", "IMG"], jpg: ["#a050dc", "IMG"], jpeg: ["#a050dc", "IMG"], heic: ["#a050dc", "IMG"], gif: ["#a050dc", "GIF"], webp: ["#a050dc", "IMG"],
  txt: ["#6e7f99", "TXT"], md: ["#6e7f99", "MD"], json: ["#6e7f99", "JSON"], xml: ["#6e7f99", "XML"], html: ["#6e7f99", "HTML"], nessus: ["#0e9f9a", "SCAN"],
};
function docIcon(name, size = "") {
  const ext = extOf(name);
  const [color, label] = DOC_COLORS[ext] || ["#8e8e93", (ext || "FILE").toUpperCase().slice(0, 4)];
  const fs = label.length > 3 ? 5.6 : 6.6;
  return `<span class="doc-icon ${size}"><svg viewBox="0 0 32 38"><path d="M5 1.2h15.2L29 10v25a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3.2a2 2 0 0 1 2-2z" fill="#fff" stroke="rgba(0,0,0,.2)" stroke-width=".8"/><path d="M20.2 1.4V8a2 2 0 0 0 2 2h6.6" fill="#eef0f3" stroke="rgba(0,0,0,.2)" stroke-width=".8"/><rect x="3" y="22.5" width="26" height="9.5" fill="${color}"/><text x="16" y="29.6" text-anchor="middle" font-family="-apple-system,Helvetica,Arial" font-weight="700" font-size="${fs}" fill="#fff">${label}</text></svg></span>`;
}
const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "bmp", "webp", "tif", "tiff", "heic"]);
const isImage = (name) => IMAGE_EXT.has(extOf(name));
function folderIcon(system = false) {
  const [b, f] = system ? ["#a7aab1", "#c4c7cd"] : ["#5aa8f2", "#86c0f8"];
  return `<svg class="folder-ico" viewBox="0 0 18 15"><path d="M1 2.3C1 1.6 1.5 1 2.2 1h4.1l1.5 1.6h8C16.5 2.6 17 3.2 17 3.9V13c0 .6-.5 1-1.1 1H2.1C1.5 14 1 13.6 1 13z" fill="${b}"/><path d="M1 4.8h16v8.1c0 .6-.5 1.1-1.1 1.1H2.1C1.5 14 1 13.5 1 12.9z" fill="${f}"/></svg>`;
}

const METHOD_TAG = (m) => {
  if (!m) return "";
  if (m.includes("人工")) return `<span class="tag">人工</span>`;
  if (m.includes("Jev")) return `<span class="tag purple">${esc(m)}</span>`;
  if (m.includes("DeepSeek")) return `<span class="tag blue">${esc(m)}</span>`;
  if (m === "已撤销") return `<span class="tag">已撤销</span>`;
  return `<span class="tag blue">${esc(m)}</span>`;
};
const STATUS_TAG = {
  archived: `<span class="tag green">已归档</span>`,
  pending_review: `<span class="tag orange">待复核</span>`,
  unmatched: `<span class="tag red">未匹配</span>`,
  duplicate: `<span class="tag">重复</span>`,
  processing: `<span class="tag blue">识别中</span>`,
  error: `<span class="tag red">出错</span>`,
  ignored: `<span class="tag">已忽略</span>`,
  skipped: `<span class="tag">已跳过</span>`,
  unpacked: `<span class="tag blue">已解压</span>`,
};
const typeName = (code) => (S.std?.types || []).find((t) => t.code === code)?.name || code || "";
const projLabel = (id) => S.projects.find((p) => p.id === id)?.label || "";
const isWin = () => String(S.st?.platform || navigator.platform || "").toLowerCase().startsWith("win");
const FM = () => (isWin() ? "资源管理器" : "访达");

/* ---------------------------------------------------------------- 路由 */
const ROUTES = { overview: renderOverview, review: renderReview, activity: renderActivity, library: renderLibrary, projects: renderProjects, settings: renderSettings, search: renderSearch };

function go(route, arg) {
  $$(".sheet-backdrop").forEach((x) => x.remove());
  S.route = route;
  $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  content.className = "content" + (["settings", "projects", "review", "overview", "activity", "search"].includes(route) ? " gray" : "");
  content.scrollTop = 0;
  const hash = route + (arg ? "/" + encodeURIComponent(arg) : "");
  if (location.hash.slice(1) !== hash) history.replaceState(null, "", "#" + hash);
  ROUTES[route](arg);
}
$$(".nav-item").forEach((a) => a.addEventListener("click", () => go(a.dataset.route)));

/* ---------------------------------------------------------------- 轮询 */
async function refreshMeta() {
  const [std, projects] = await Promise.all([S.std ? S.std : api("/api/standards"), api("/api/projects")]);
  S.std = std;
  S.projects = projects;
}

async function tick(first = false) {
  let st;
  try { st = await api("/api/state"); } catch (e) {
    $("#watch-text").textContent = "服务未连接";
    $("#watch-dot").className = "dot";
    return;
  }
  S.st = st;
  if (st.previous_data && !S.prevNoticed) {
    S.prevNoticed = true;
    toast("已接着使用之前的数据", `设置、项目和归档记录来自 ${st.previous_data}`);
  }
  const c = st.counts;
  const rv = c.review + c.unmatched;
  const b = $("#badge-review");
  b.textContent = rv || "";
  b.className = "badge" + (rv ? " alert" : "");
  $("#badge-files").textContent = c.files || "";
  $("#badge-projects").textContent = c.projects || "";
  const w = st.watcher;
  $("#watch-dot").className = "dot" + (w.running ? " on" : "");
  $("#watch-text").textContent = w.running ? `${w.mode}${st.sources ? ` · +${st.sources} 个来源` : ""}${st.queue ? ` · 处理中 ${st.queue}` : ""}` : "自动整理已暂停";
  $("#watch-path").textContent = w.path.replace(/^\/Users\/[^/]+/, "~");
  $("#pill-jev").className = "ai-pill" + (st.ai.jev ? " on" : "");
  $("#pill-ds").className = "ai-pill" + (st.ai.deepseek ? " on" : "");
  $("#pill-ocr").className = "ai-pill" + (st.ai.ocr ? " on" : "");
  $("#pill-ocr").title = `图片与扫描件文字识别：${st.ai.ocr ? "已开启" : (st.ocr?.ready ? "已关闭" : "未安装")}`;

  const sig = JSON.stringify([c, st.queue]);
  if (sig === S.sig && !first) return;
  S.sig = sig;
  let jobs = [];
  try { jobs = await api("/api/jobs?limit=20"); } catch (e) { return; }
  const maxId = jobs.reduce((m, j) => Math.max(m, j.id), 0);
  if (S.lastJobId === null) S.lastJobId = maxId;
  else if (maxId > S.lastJobId) {
    const fresh = jobs.filter((j) => j.id > S.lastJobId && j.status !== "processing").reverse();
    if (fresh.length > 3) toast(`处理了 ${fresh.length} 个文件`, `${fresh.filter((j) => j.status === "archived").length} 个已自动归档`);
    else fresh.forEach((j) => {
      if (j.status === "archived") toast("已自动归档", j.result?.name || j.original_name);
      else if (j.status === "pending_review") toast("需要复核", `${j.original_name}：项目或类型拿不准`);
      else if (j.status === "unmatched") toast("未找到对应项目", j.original_name);
      else if (j.status === "duplicate") toast("发现重复文件", `${j.original_name} 已存在，移入 _重复文件`);
    });
    if (fresh.length) S.lastJobId = Math.max(...fresh.map((j) => j.id));
  }
  if (S.route === "overview") updateOverview(jobs);
  if (S.route === "review") loadReview(true);
  if (S.route === "activity" && !first) renderActivity();
}

/* ---------------------------------------------------------------- 概览 */
function renderOverview() {
  toolbar("概览", S.st ? `归档库：${S.st.root.replace(/^\/Users\/[^/]+/, "~")}` : "",
    `<button class="btn" id="tb-scan">${ic("refresh")}扫描收件箱</button><button class="btn" id="tb-inbox">${ic("tray")}打开收件箱</button>`);
  $("#tb-scan").onclick = async () => { const r = await api("/api/scan", { method: "POST" }).catch(fail); if (r) toast("已扫描收件箱", r.found ? `发现 ${r.found} 个新文件` : "没有新文件"); };
  $("#tb-inbox").onclick = () => openPath(S.st.inbox, "open");
  content.innerHTML = `<div class="page">
    ${S.projects.length ? "" : `<div class="group" style="margin-bottom:16px"><div class="row"><span style="color:var(--orange)">${ic("warning")}</span><div class="grow"><b>还没有项目</b><div class="desc">先在「项目」里添加或导入 CRM 项目，系统才知道该把文件归到哪里。</div></div><button class="btn primary" onclick="go('projects')">添加项目</button></div></div>`}
    <div class="drop" id="drop-card">
      <div class="tray">${ic("tray")}</div>
      <div><h2>把文件拖到这里</h2><p>或直接放进「_收件箱」文件夹，系统会识别内容、按规范重命名并归入项目。</p></div>
      <div class="drop-actions">
        <button class="btn primary lg" id="pick-files">${ic("plus")}选择文件…</button>
        <div class="drop-to">归档到 <span class="combo-host" id="drop-project-host"></span><input type="hidden" id="drop-project" value=""></div>
      </div>
    </div>
    <div class="stats" id="stats"></div>
    <div class="group-title">最近处理 <span class="processing hidden" id="proc"><span class="spinner"></span><span id="proc-n"></span></span><button class="btn plain more" onclick="go('activity')">全部记录</button></div>
    <div class="group" id="recent"><div class="empty">${ic("tray")}<h3>还没有处理过文件</h3>拖入文件试试看</div></div>
  </div>`;
  $("#pick-files").onclick = () => $("#file-input").click();
  makeCombo($("#drop-project-host"), $("#drop-project"), { options: projectChoices([], "自动识别项目"), allowEmpty: true, placeholder: "自动识别项目", minWidth: 400 });
  updateStats();
  api("/api/jobs?limit=14").then(updateOverview).catch(() => {});
}

function updateStats() {
  const el = $("#stats");
  if (!el || !S.st) return;
  const c = S.st.counts;
  const rate = c.all_jobs ? Math.round((c.all_auto / c.all_jobs) * 100) : null;
  el.innerHTML = `
    <div class="stat blue"><div class="k">${ic("archive")}今日归档</div><div class="v">${c.today_archived}<small>个</small></div></div>
    <div class="stat green"><div class="k">${ic("bolt")}自动归档率</div><div class="v">${rate === null ? "—" : rate}<small>${rate === null ? "" : "%"}</small></div></div>
    <div class="stat orange link" onclick="S.reviewTab='pending_review';go('review')"><div class="k">${ic("review")}待复核</div><div class="v">${c.review}<small>个</small></div></div>
    <div class="stat red link" onclick="S.reviewTab='unmatched';go('review')"><div class="k">${ic("question")}未匹配</div><div class="v">${c.unmatched}<small>个</small></div></div>`;
}

function updateOverview(jobs) {
  updateStats();
  const proc = $("#proc");
  if (proc) {
    proc.classList.toggle("hidden", !S.st?.queue);
    $("#proc-n").textContent = S.st?.queue ? `正在处理 ${S.st.queue} 个文件` : "";
  }
  const box = $("#recent");
  if (!box) return;
  if (!jobs.length) return;
  box.innerHTML = jobs.slice(0, 14).map(jobRow).join("");
  bindJobRows(box);
}

function jobRow(j) {
  const s = j.suggestion || {};
  const r = j.result || {};
  let name = j.original_name, sub = "", right = "";
  if (j.status === "archived") {
    name = r.name || j.original_name;
    sub = `${j.original_name} → ${r.project || ""} / ${r.stage || ""}${r.replaced ? ` · 替换 ${r.replaced}` : ""}`;
    right = `${METHOD_TAG(j.method)}`;
  } else if (j.status === "pending_review") {
    sub = `建议：${projLabel(s.project_id) || "—"} · ${typeName(s.doc_type)} · 把握 ${Math.round((j.confidence || 0) * 100)}%`;
  } else if (j.status === "unmatched") {
    sub = "没有找到对应项目，需要手动指定";
  } else if (j.status === "duplicate") {
    sub = `与已有文件相同：${r.existing_name || ""}`;
  } else if (j.status === "error") {
    sub = j.error || "处理出错";
  } else if (j.status === "processing") {
    sub = "正在识别…";
  } else if (j.status === "ignored") {
    sub = r.ignored_reason ? `来自${j.source}：${r.ignored_reason}，已忽略（原文件仍在原处）` : "已移出列表，文件保留在原位置";
  } else if (j.status === "skipped") {
    sub = `来自${j.source}，和已有文件「${r.existing_name || ""}」相同，已跳过`;
  } else if (j.status === "unpacked") {
    sub = `解压出 ${r.count || 0} 个文件，逐个识别归档${r.kept ? " · 原压缩包在 _原始压缩包" : ""}`;
  }
  const acts = [];
  if (j.status === "archived") {
    acts.push(`<button class="btn plain icon" title="快速查看" data-ql="${esc(r.path)}">${ic("eye")}</button>`);
    acts.push(`<button class="btn plain icon" title="在${FM()}中显示" data-reveal="${esc(r.path)}">${ic("folder")}</button>`);
    acts.push(`<button class="btn plain icon" title="撤销归档" data-undo="${j.id}">${ic("undo")}</button>`);
  } else if (["pending_review", "unmatched", "error"].includes(j.status)) {
    acts.push(`<button class="btn plain" data-goreview="${j.status === "pending_review" ? "pending_review" : "unmatched"}">去处理</button>`);
  } else if (j.status === "duplicate") {
    acts.push(`<button class="btn plain icon" title="在${FM()}中显示已有文件" data-reveal="${esc(r.existing_path || "")}">${ic("folder")}</button>`);
  } else if (j.status === "unpacked" && r.kept) {
    acts.push(`<button class="btn plain icon" title="在${FM()}中显示原压缩包" data-reveal="${esc(r.kept)}">${ic("folder")}</button>`);
  } else if (j.status === "ignored" && j.origin_exists) {
    acts.push(`<button class="btn plain" data-reimport="${j.id}" title="从原位置再复制一份，放进待复核">拿来归档</button>`);
  }
  return `<div class="file-row">${docIcon(j.original_name)}<div class="meta"><div class="name selectable">${esc(name)}</div><div class="sub">${esc(sub)}</div></div>
    <div class="right"><div class="acts">${acts.join("")}</div>${right}${STATUS_TAG[j.status] || ""}<span style="min-width:62px;text-align:right">${fmtTime(j.decided_at || j.created_at)}</span></div></div>`;
}

function bindJobRows(box) {
  $$("[data-ql]", box).forEach((b) => (b.onclick = () => openPath(b.dataset.ql, "quicklook")));
  $$("[data-reveal]", box).forEach((b) => (b.onclick = () => openPath(b.dataset.reveal, "reveal")));
  $$("[data-goreview]", box).forEach((b) => (b.onclick = () => { S.reviewTab = b.dataset.goreview; go("review"); }));
  $$("[data-reimport]", box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api(`/api/jobs/${b.dataset.reimport}/reimport`, { method: "POST" }); toast("已拿来归档", "正在识别，稍后在「待复核」里确认"); S.sig = ""; tick(); }
    catch (e) { b.disabled = false; fail(e); }
  }));
  $$("[data-undo]", box).forEach((b) => (b.onclick = async () => {
    try {
      await api(`/api/jobs/${b.dataset.undo}/undo`, { method: "POST" });
      toast("已撤销", "文件已移到「_待复核」，旧版本已恢复");
      S.sig = ""; tick();
    } catch (e) { fail(e); }
  }));
}

async function openPath(path, mode = "open") {
  if (!path) return;
  try { await api("/api/open", { json: { path, mode } }); } catch (e) { fail(e); }
}

/* ---------------------------------------------------------------- 上传 */
async function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  const pid = $("#drop-project")?.value;
  if (pid) fd.append("project_id", pid);
  try {
    const r = await api("/api/upload", { method: "POST", body: fd });
    toast(`已接收 ${r.accepted} 个文件`, "正在识别内容并归档…");
    S.sig = ""; setTimeout(() => tick(), 600);
  } catch (e) { fail(e); }
}
$("#file-input").addEventListener("change", (e) => { uploadFiles(Array.from(e.target.files)); e.target.value = ""; });
let dragDepth = 0;
window.addEventListener("dragenter", (e) => { if (e.dataTransfer?.types?.includes("Files")) { dragDepth++; $("#dropmask").classList.remove("hidden"); } });
window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("#dropmask").classList.add("hidden"); });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault(); dragDepth = 0; $("#dropmask").classList.add("hidden");
  const files = Array.from(e.dataTransfer?.files || []).filter((f) => f.size > 0 || f.type);
  if (!files.length) return toast("没有可上传的文件", "文件夹请直接放进「_收件箱」，系统会整批处理");
  uploadFiles(files);
});

/* ---------------------------------------------------------------- 模糊匹配（关键字 / 不连续 / 拼音首字母） */
const PY = (() => {
  let coll = null;
  try { coll = new Intl.Collator("zh-Hans-CN"); } catch (e) { coll = null; }
  const B = Array.from("阿八嚓咑妸发旮哈讥咔垃妈拿喔趴七然仨他挖夕丫匝");
  const L = "abcdefghjklmnopqrstwxyz";
  const cache = new Map();
  return (ch) => {
    if (!/[一-鿿]/.test(ch)) return ch.toLowerCase();
    if (!coll) return ch;
    let r = cache.get(ch);
    if (r !== undefined) return r;
    r = ch;
    for (let i = 0; i < B.length; i++) { if (coll.compare(ch, B[i]) >= 0) r = L[i]; else break; }
    cache.set(ch, r);
    return r;
  };
})();

function fzPrep(s) {
  const chars = Array.from(String(s ?? ""));
  return { chars, low: chars.map((c) => c.toLowerCase()), ini: null };
}
function fzIni(P) { if (!P.ini) P.ini = P.chars.map(PY); return P.ini; }
function fzIndex(arr, t) {
  outer: for (let i = 0; i <= arr.length - t.length; i++) {
    for (let k = 0; k < t.length; k++) if (arr[i + k] !== t[k]) continue outer;
    return i;
  }
  return -1;
}
function fzSubseq(arr, t) {
  let best = null;
  for (let s = 0; s < arr.length; s++) {
    if (arr[s] !== t[0]) continue;
    const idx = [s];
    let p = s + 1;
    for (let k = 1; k < t.length; k++) {
      while (p < arr.length && arr[p] !== t[k]) p++;
      if (p >= arr.length) { idx.length = 0; break; }
      idx.push(p++);
    }
    if (idx.length === t.length && (!best || idx[idx.length - 1] - idx[0] < best[best.length - 1] - best[0])) best = idx;
  }
  return best;
}
const fzRange = (i, n) => Array.from({ length: n }, (_, k) => i + k);

/** 单个词与一段文字的匹配：连续 > 拼音首字母 > 按顺序不连续 */
function fzTerm(t, P) {
  const tl = Array.from(t);
  if (!tl.length || !P.chars.length) return null;
  let i = fzIndex(P.low, tl);
  if (i >= 0) return { score: 100 + (i === 0 ? 15 : 0) + tl.length * 3 - Math.min(i, 20) * 0.3, idx: fzRange(i, tl.length) };
  if (/^[a-z]+$/.test(t) && tl.length >= 2) {
    const ini = fzIni(P);
    i = fzIndex(ini, tl);
    if (i >= 0) return { score: 80 + (i === 0 ? 10 : 0) + tl.length * 2, idx: fzRange(i, tl.length) };
    // 首字母允许少量隔字（如 cwkjdb 对「澄湾科技-等保」），隔太多就不算
    const sub = fzSubseq(ini, tl);
    if (sub && sub[sub.length - 1] - sub[0] + 1 <= Math.floor(tl.length * 1.5) + 1) return { score: 50 + 20 * tl.length / (sub[sub.length - 1] - sub[0] + 1), idx: sub };
  }
  if (tl.length >= 2) {
    const sub = fzSubseq(P.low, tl);
    if (sub) {
      const span = sub[sub.length - 1] - sub[0] + 1;
      // 纯字母数字（多半是编号片段）只容许很小的间隔，免得乱配到随机的项目编号里
      const limit = /^[\x00-\x7f]+$/.test(t) ? tl.length + 3 : tl.length * 4 + 6;
      if (span <= limit) return { score: 40 + 20 * tl.length / span, idx: sub };
    }
  }
  return null;
}
/** 多个词（空格分隔）都要匹配到某个字段；返回总分 */
function fzMatch(q, fields) {
  const terms = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return { score: 0 };
  let total = 0;
  for (const t of terms) {
    let best = 0;
    fields.forEach((f, k) => { const m = fzTerm(t, f); if (m) best = Math.max(best, m.score * (k === 0 ? 1 : 0.92)); });
    if (!best) return null;
    total += best;
  }
  return { score: total };
}
/** 把匹配到的字标亮 */
function fzHighlight(text, q) {
  const P = fzPrep(text);
  const hit = new Set();
  for (const t of String(q || "").toLowerCase().split(/\s+/).filter(Boolean)) { const m = fzTerm(t, P); if (m) m.idx.forEach((i) => hit.add(i)); }
  return P.chars.map((c, i) => (hit.has(i) ? `<mark>${esc(c)}</mark>` : esc(c))).join("").replace(/<\/mark><mark>/g, "");
}

/* ---------------------------------------------------------------- 可搜索的选择框 */
let comboOpen = null;
function closeCombo(refocus = false) {
  if (!comboOpen) return;
  const { pop, btn } = comboOpen;
  pop.remove(); btn.classList.remove("open"); comboOpen = null;
  if (refocus) btn.focus();
}
document.addEventListener("mousedown", (e) => { if (comboOpen && !comboOpen.pop.contains(e.target) && !comboOpen.btn.contains(e.target)) closeCombo(); });
window.addEventListener("resize", () => closeCombo());
content.addEventListener("scroll", () => closeCombo(), { passive: true });

function makeCombo(host, input, opts) {
  const options = opts.options;
  options.forEach((o) => { o._f = o._f || (o.keys || [o.label]).map(fzPrep); });
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "combo-btn";
  const render = () => {
    const cur = options.find((o) => o.value === String(input.value ?? ""));
    btn.innerHTML = cur && (cur.value || opts.allowEmpty)
      ? `<span class="cl">${esc(cur.label)}</span>${cur.short ? `<span class="cs">${esc(cur.short)}</span>` : ""}`
      : `<span class="ph">${esc(opts.placeholder || "请选择…")}</span>`;
    btn.title = cur ? `${cur.label}${cur.sub ? "\n" + cur.sub : ""}` : "";
  };
  render();
  host.innerHTML = "";
  host.appendChild(btn);
  btn.addEventListener("click", () => (comboOpen?.btn === btn ? closeCombo() : open("")));
  btn.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); e.stopPropagation(); open(""); }
    else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); e.stopPropagation(); open(e.key); }
  });

  function open(prefill) {
    closeCombo();
    const pop = document.createElement("div");
    pop.className = "combo-pop";
    pop.innerHTML = `<label class="search combo-search">${ic("search")}<input placeholder="${esc(opts.searchHint || "关键字或拼音首字母，如 xbk")}" autocomplete="off" spellcheck="false"></label><div class="combo-list"></div>${opts.footer ? `<button type="button" class="combo-foot">${ic("plus")}<span></span></button>` : ""}`;
    document.body.appendChild(pop);
    btn.classList.add("open");
    comboOpen = { pop, btn };
    const r = btn.getBoundingClientRect();
    const w = Math.min(window.innerWidth - 24, Math.max(r.width, opts.minWidth || 340));
    pop.style.width = `${w}px`;
    pop.style.left = `${Math.max(12, Math.min(r.left, window.innerWidth - w - 12))}px`;
    const below = window.innerHeight - r.bottom - 12, above = r.top - 12;
    if (below >= 280 || below >= above) { pop.style.top = `${r.bottom + 4}px`; pop.style.maxHeight = `${Math.min(400, below)}px`; }
    else { pop.style.bottom = `${window.innerHeight - r.top + 4}px`; pop.style.maxHeight = `${Math.min(400, above)}px`; }
    const inp = $("input", pop), list = $(".combo-list", pop);
    let rows = [], active = 0;
    const draw = (keepActive = false, composing = false) => {
      let q = inp.value.trim().replace(/['’]/g, "");
      if (composing) q = q.replace(/\s+/g, "");
      if (!q) rows = options.map((o) => ({ o }));
      else {
        const seen = new Set();
        rows = [];
        for (const o of options) {
          if ((!o.value && !opts.allowEmpty) || seen.has(o.value)) continue;
          const m = fzMatch(q, o._f);
          if (m) { rows.push({ o, score: m.score }); seen.add(o.value); }
        }
        rows.sort((a, b) => b.score - a.score);
        rows = rows.slice(0, 200);
      }
      if (!keepActive) {
        const cur = rows.findIndex((x) => x.o.value === String(input.value ?? ""));
        active = q ? 0 : Math.max(0, cur);
      }
      let html = "", last = null;
      rows.forEach(({ o }, i) => {
        if (!q && o.group !== last) { last = o.group; if (o.group) html += `<div class="combo-group">${esc(o.group)}</div>`; }
        html += `<div class="combo-opt ${i === active ? "on" : ""} ${o.value === String(input.value ?? "") ? "cur" : ""}" data-i="${i}">
          <div class="l">${q ? fzHighlight(o.label, q) : esc(o.label)}</div>${o.sub ? `<div class="s">${q ? fzHighlight(o.sub, q) : esc(o.sub)}</div>` : ""}</div>`;
      });
      list.innerHTML = html || `<div class="combo-empty">没有匹配的选项</div>`;
      if (opts.footer) $(".combo-foot span", pop).textContent = q ? opts.footer.labelFor(q) : opts.footer.label;
      $(".combo-opt.on", list)?.scrollIntoView({ block: "nearest" });
    };
    const pick = (i) => {
      const row = rows[i];
      if (!row) return;
      input.value = row.o.value;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      render();
      closeCombo(true);
      opts.onPick?.(row.o);
    };
    list.addEventListener("mousemove", (e) => {
      const it = e.target.closest(".combo-opt");
      if (!it || Number(it.dataset.i) === active) return;
      $(".combo-opt.on", list)?.classList.remove("on");
      it.classList.add("on");
      active = Number(it.dataset.i);
    });
    list.addEventListener("mousedown", (e) => { const it = e.target.closest(".combo-opt"); if (it) { e.preventDefault(); pick(Number(it.dataset.i)); } });
    $(".combo-foot", pop)?.addEventListener("mousedown", (e) => { e.preventDefault(); const q = inp.value.trim(); closeCombo(); opts.footer.onClick(q); });
    // 中文输入法组字时（如 x'b'k）也实时过滤：去掉分隔符当作拼音首字母；上屏后再按汉字过滤
    inp.addEventListener("input", (e) => draw(false, e.isComposing));
    inp.addEventListener("compositionend", () => draw());
    inp.addEventListener("keydown", (e) => {
      if (e.isComposing) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = Math.max(0, Math.min(rows.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
        draw(true);
      } else if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); pick(active); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeCombo(true); }
      else if (e.key === "Tab") closeCombo();
    });
    inp.value = prefill || "";
    draw();
    inp.focus(); // 立即聚焦，点开后马上打字也不会丢字
    if (prefill) inp.setSelectionRange(prefill.length, prefill.length);
  }
  return { render, open };
}

const sortZh = (a, b) => String(a).localeCompare(String(b), "zh-Hans-CN");
function projectChoice(p, group, prob) {
  return {
    value: String(p.id), label: `${p.customer_short} · ${p.short_name}`, short: p.project_no,
    sub: `${p.project_no}${p.biz_line ? " · " + p.biz_line : ""}${p.status === "已结项" ? " · 已结项" : ""}${prob ? ` · 建议 ${Math.round(prob * 100)}%` : ""}`,
    group, keys: [p.short_name, p.customer_short, p.project_no, p.name, p.customer_full || "", (p.aliases || []).join(" "), p.biz_line || ""],
  };
}
function projectChoices(suggest = [], emptyLabel = null) {
  const out = [];
  if (emptyLabel !== null) out.push({ value: "", label: emptyLabel, group: "", keys: [emptyLabel] });
  const byId = new Map(S.projects.map((p) => [p.id, p]));
  (suggest || []).forEach((c) => { const p = byId.get(c.id); if (p) out.push(projectChoice(p, "建议", c.p)); });
  [...S.projects].sort((a, b) => sortZh(a.customer_short, b.customer_short) || sortZh(a.short_name, b.short_name))
    .forEach((p) => out.push(projectChoice(p, p.customer_short)));
  return out;
}
function typeChoices() {
  const stages = S.std?.stages || [];
  const order = (t) => { const i = stages.indexOf(t.stage.split("/")[0]); return i < 0 ? 99 : i; };
  return [...(S.std?.types || [])].filter((t) => t.enabled !== false).sort((a, b) => order(a) - order(b))
    .map((t) => ({ value: t.code, label: t.name, short: t.code, sub: `${t.code} · ${t.stage}`, group: t.stage, keys: [t.name, t.code, (t.keywords || []).join(" "), t.stage] }));
}

/** 类型选择框：底部可「新增类型」，新增后自动选中 */
function mountTypeCombo(host, input) {
  host._mount = () => mountTypeCombo(host, input);
  return makeCombo(host, input, {
    options: typeChoices(), placeholder: "选择类型…", minWidth: 340,
    footer: {
      label: "没有合适的？新增类型…", labelFor: (q) => `新增类型「${q}」…`,
      onClick: (q) => typeSheet(null, { name: q, onSaved: (code) => { input.value = code; input.dispatchEvent(new Event("change", { bubbles: true })); } }),
    },
  });
}
async function reloadTypes() {
  S.std = await api("/api/standards");
  $$('[data-combo="type"]').forEach((h) => h._mount?.());
}
const TYPE_STAGE_NAME = (st) => (st === "03_过程文档/证据" ? "03_过程文档/证据（保留原文件名）" : st);
function suggestTypeCode(name, stage) {
  const pre = S.std?.stage_prefix?.[stage] || "DOC";
  const ini = Array.from(name || "").map((c) => (/[一-鿿]/.test(c) ? PY(c) : /[a-z0-9]/i.test(c) ? c : "")).join("").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
  const used = new Set((S.std?.types || []).map((t) => t.code));
  let code = `${pre}-${ini.length >= 2 ? ini : "NEW"}`, n = 2;
  while (used.has(code)) code = `${pre}-${(ini.length >= 2 ? ini : "NEW").slice(0, 8)}${n++}`;
  return code;
}
/** 新增 / 修改类型。t = null 为新增；内置类型只能追加关键词 */
function typeSheet(t, o = {}) {
  const isNew = !t, builtin = !!t?.builtin;
  const stages = S.std?.type_stages || [];
  const stage0 = t?.stage || o.stage || "03_过程文档";
  const kwText = builtin ? (t.extra_keywords || []).join("、") : (t?.keywords || []).filter((k) => k !== t?.name).join("、");
  const html = `<h2>${isNew ? "新增类型" : builtin ? `内置类型 · ${esc(t.name)}` : "修改类型"}</h2>
  <p class="intro">${isNew ? "新类型会出现在类型选择框里，并参与自动识别；类型码出现在文件名里。" : builtin ? "内置类型的名称和目录不能改，可以追加识别关键词。" : "修改只影响之后归档的文件，已归档的文件不会改名。"}</p>
  <div class="body"><div class="grid">
    <label>类型名称</label><input class="field" name="name" value="${esc(t?.name || o.name || "")}" maxlength="20" placeholder="如：服务生效单" ${builtin ? "disabled" : ""}>
    <label>归档目录</label><select class="field" name="stage" ${builtin ? "disabled" : ""}>${stages.map((st) => `<option value="${esc(st)}" ${st === stage0 ? "selected" : ""}>${esc(TYPE_STAGE_NAME(st))}</option>`).join("")}</select>
    <label>类型码</label><input class="field mono" name="code" value="${esc(t?.code || "")}" maxlength="19" ${isNew ? "" : "disabled"} style="text-transform:uppercase">
    ${isNew ? `<div class="hint">按目录和名称自动生成，可以改；保存后不能再改</div>` : ""}
    <label>${builtin ? "追加关键词" : "识别关键词"}</label><textarea class="field" name="kw" rows="3" placeholder="文件名或正文里出现这些词就判为这个类型，用顿号隔开，如：生效单、开通确认">${esc(kwText)}</textarea>
    ${builtin ? `<div class="hint">内置关键词：${esc((t.keywords || []).join("、"))}</div>` : `<div class="hint">类型名称本身会自动算作关键词</div>`}
    ${builtin ? "" : `<span></span><label class="check-line"><input type="checkbox" name="series" ${t?.series ? "checked" : ""}>每份单独存放，不互相替代版本（如周报、纪要）</label>`}
    ${t && !builtin ? `<span></span><label class="check-line"><input type="checkbox" name="enabled" ${t.enabled !== false ? "checked" : ""}>启用（停用后不再识别和出现在选择框里，已归档文件不受影响）</label>
      <span></span><div><button type="button" class="btn plain danger" data-del style="padding:0">删除这个类型</button></div>` : ""}
  </div></div>`;
  const bd = sheet(html, async (root) => {
    const v = (n) => $(`[name="${n}"]`, root);
    const body = builtin ? { extra_keywords: v("kw").value }
      : { name: v("name").value.trim(), stage: v("stage").value, keywords: v("kw").value, series: v("series").checked,
          ...(isNew ? { code: v("code").value.trim().toUpperCase() } : { enabled: v("enabled").checked }) };
    const r = isNew ? await api("/api/types", { json: body }) : await api(`/api/types/${encodeURIComponent(t.code)}`, { method: "PUT", json: body });
    o.onSaved?.(r.code);
    await reloadTypes();
    toast(isNew ? "已新增类型" : "类型已更新", isNew ? `${body.name}（${r.code}）` : (builtin ? `${t.name}：追加关键词已保存` : body.name));
    if (S.route === "settings") renderSettings();
  }, isNew ? "新增" : "存储");
  if (isNew) {
    const name = $('[name="name"]', bd), stage = $('[name="stage"]', bd), code = $('[name="code"]', bd);
    let touched = false;
    const auto = () => { if (!touched) code.value = suggestTypeCode(name.value.trim(), stage.value); };
    code.addEventListener("input", () => { touched = true; });
    name.addEventListener("input", auto); stage.addEventListener("change", auto); auto();
  }
  $("[data-del]", bd)?.addEventListener("click", async () => {
    try {
      await api(`/api/types/${encodeURIComponent(t.code)}`, { method: "DELETE" });
      bd.remove(); await reloadTypes(); toast("已删除类型", t.name);
      if (S.route === "settings") renderSettings();
    } catch (e) { fail(e); }
  });
  return bd;
}

/* ---------------------------------------------------------------- 待复核 */
function renderReview() {
  const c = S.st?.counts || {};
  toolbar("待复核", "AI 拿不准的文件，确认后按规范归档", `<button class="btn" id="tb-rerun-all">${ic("sparkles")}全部重新识别</button>`);
  $("#tb-rerun-all").onclick = async () => {
    const cards = $$(".card[data-job]");
    for (const el of cards) await api(`/api/jobs/${el.dataset.job}/rerun`, { method: "POST" }).catch(() => {});
    toast("已提交重新识别", `${cards.length} 个文件`);
  };
  content.innerHTML = `<div class="page" style="max-width:900px">
    <div class="review-head"><div class="segmented" id="rv-tabs">
      <button data-t="pending_review">待复核 <span class="n" id="n-pr">${c.review ?? ""}</span></button>
      <button data-t="unmatched">未匹配 <span class="n" id="n-un">${c.unmatched ?? ""}</span></button>
      <button data-t="duplicate">重复文件</button></div>
      <div class="spacer" style="flex:1"></div><span class="desc" style="color:var(--secondary);font-size:11.5px">按 <span class="kbd">⏎</span> 确认当前卡片</span></div>
    <div id="rv-list"></div></div>`;
  $$("#rv-tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.t === S.reviewTab);
    b.onclick = () => { S.reviewTab = b.dataset.t; renderReview(); };
  });
  loadReview(false);
}

async function loadReview(soft) {
  const list = $("#rv-list");
  if (!list) return;
  const c = S.st?.counts || {};
  if ($("#n-pr")) { $("#n-pr").textContent = c.review ?? ""; $("#n-un").textContent = c.unmatched ?? ""; }
  const status = S.reviewTab === "unmatched" ? "unmatched,error" : S.reviewTab;
  let jobs;
  try { jobs = await api(`/api/jobs?status=${status}&limit=200`); } catch (e) { return fail(e); }
  if (S.reviewTab === "duplicate") {
    list.innerHTML = jobs.length ? `<div class="group">${jobs.map((j) => `<div class="file-row">${docIcon(j.original_name)}<div class="meta"><div class="name">${esc(j.original_name)}</div><div class="sub">与已有文件相同：${esc(j.result?.existing_name || "")}</div></div>
      <div class="right"><div class="acts" style="opacity:1"><button class="btn" data-reveal="${esc(j.staged_path)}">${ic("folder")}显示重复件</button><button class="btn" data-reveal="${esc(j.result?.existing_path || "")}">显示已有文件</button><button class="btn" data-again="${j.id}">仍然归档</button><button class="btn" data-dismiss="${j.id}">移出列表</button></div><span>${fmtTime(j.created_at)}</span></div></div>`).join("")}</div>
      <p class="note">重复文件按内容哈希判断，已移到「_重复文件」文件夹，不会删除。确认不需要后可自行清理。</p>`
      : `<div class="empty">${ic("copy")}<h3>没有重复文件</h3></div>`;
    $$("[data-reveal]", list).forEach((b) => (b.onclick = () => openPath(b.dataset.reveal, "reveal")));
    $$("[data-again]", list).forEach((b) => (b.onclick = async () => {
      try { await api(`/api/jobs/${b.dataset.again}/rerun`, { method: "POST" }); toast("已重新识别", "将作为新文件处理"); S.sig = ""; tick(); setTimeout(() => loadReview(false), 800); } catch (e) { fail(e); }
    }));
    $$("[data-dismiss]", list).forEach((b) => (b.onclick = () => {
      const j = jobs.find((x) => String(x.id) === b.dataset.dismiss);
      if (j) dismissJob(j, b.closest(".file-row"));
    }));
    return;
  }
  const ids = new Set(jobs.map((j) => String(j.id)));
  $$(".card[data-job]", list).forEach((el) => { if (!ids.has(el.dataset.job)) el.remove(); });
  $(".empty", list)?.remove();
  for (const j of jobs.slice().reverse()) {
    const existing = $(`.card[data-job="${j.id}"]`, list);
    if (existing) {
      if (!soft || existing.dataset.sig !== cardSig(j)) existing.replaceWith(reviewCard(j));
      continue;
    }
    list.prepend(reviewCard(j));
  }
  if (!jobs.length) {
    list.innerHTML = `<div class="empty">${ic("check")}<h3>${S.reviewTab === "unmatched" ? "没有未匹配的文件" : "全部处理完了"}</h3>新文件识别有把握时会自动归档</div>`;
  }
}
const cardSig = (j) => `${j.status}|${j.confidence}|${j.method}|${j.staged_path}|${j.missing ? 1 : 0}`;

function removeCard(el) {
  el.style.transition = "opacity .25s, transform .25s";
  el.style.opacity = "0"; el.style.transform = "translateX(30px)";
  setTimeout(() => {
    const next = el.nextElementSibling; el.remove(); next?.focus?.();
    const list = $("#rv-list");
    if (list && !$(".card, .file-row", list)) loadReview(false);
  }, 250);
}

function dismissJob(j, el) {
  const name = j.current_name || j.original_name;
  const folder = j.status === "duplicate" ? "_重复文件" : j.status === "pending_review" ? "_待复核" : "_未匹配";
  const intro = j.missing
    ? "这个文件已经找不到了，移出后只删除这条待处理记录。"
    : `文件不会被删除，仍保留在「${folder}」文件夹里，之后可以在${FM()}中自行处理。`;
  sheet(`<h2>移出列表？</h2><p class="intro">${esc(intro)}</p><div class="body"><div class="selectable" style="font-size:12px;color:var(--secondary);word-break:break-all;padding-bottom:4px">${esc(name)}</div></div>`,
    async () => {
      const r = await api(`/api/jobs/${j.id}/dismiss`, { method: "POST" });
      toast("已移出列表", r.rel ? `文件位置：${r.rel}` : name);
      removeCard(el);
      S.sig = ""; tick();
    }, "移出");
}

function reviewCard(j) {
  const s = j.suggestion || {};
  const el = document.createElement("div");
  el.className = "card";
  el.tabIndex = -1;
  el.dataset.job = j.id;
  el.dataset.sig = cardSig(j);
  const conf = Math.round((j.confidence || 0) * 100);
  const color = conf >= 80 ? "var(--green)" : conf >= 60 ? "var(--orange)" : "var(--red)";
  const ev = (s.evidence || []).map((x) => `<span class="chip ${/不一致|多个|无法|需确认/.test(x) ? "warn" : ""}">${esc(x)}</span>`).join("");
  const errs = (s.errors || []).concat(j.error ? [j.error] : []);
  const statuses = (S.std?.statuses || ["草稿", "内审", "送审", "正式", "签字"]);
  const curName = j.current_name || j.original_name;
  const renamed = curName && j.original_name && curName !== j.original_name && !j.missing;
  el.innerHTML = `
    <div class="card-top">${isImage(curName) && !j.missing && j.staged_path ? `<img class="thumb" alt="" loading="lazy" data-act="ql" title="快速查看" src="/api/download?path=${encodeURIComponent(j.staged_path)}">` : docIcon(curName)}
      <div class="meta"><div class="name selectable">${esc(curName)}</div><div class="sub">${renamed ? `已改名（原名 ${esc(j.original_name)}） · ` : ""}${fmtSize(j.size)} · ${esc(j.source || "")} · ${fmtTime(j.created_at)}${s.title_source && !renamed ? ` · 标题来自${esc(s.title_source)}` : ""}</div></div>
      <div class="meter" title="综合把握">${j.status === "unmatched" ? "未找到项目" : `把握 ${conf}%`}<span class="bar"><i style="width:${Math.max(conf, 4)}%;background:${color}"></i></span></div>
      <button class="btn plain icon" title="快速查看（空格）" data-act="ql">${ic("eye")}</button>
      <button class="btn plain icon" title="在${FM()}中显示" data-act="reveal">${ic("folder")}</button>
    </div>
    ${ev ? `<div class="chips">${ev}</div>` : ""}
    ${s.summary ? `<div class="snippet">${esc(s.summary)}</div>` : s.snippet ? `<div class="snippet">${s.ocr ? `<span class="ocr-tag">${ic("photo")}图中文字</span>` : ""}${esc(s.snippet)}</div>` : ""}
    ${j.missing ? `<div class="error-line">${ic("warning")} 找不到这个文件：它可能被移走、删除，或改名后又修改了内容。可以把文件重新放进收件箱，再把这一条「移出列表」。</div>`
      : errs.length ? `<div class="error-line">${ic("warning")} ${esc(errs.join("；"))}</div>` : ""}
    ${renamed ? `<div class="chips"><span class="chip">文件已改名，可点「重新识别」按新名字识别</span></div>` : ""}
    ${(s.archive?.can_unpack || s.archive?.status === "password") && !j.missing ? `<div class="arch-row">${ic("archive")}<span class="grow">${esc(s.archive.reason)}</span>
      ${s.archive.status === "password" ? `<input class="field mono" type="password" data-pw placeholder="解压密码" autocomplete="off"><label class="remember-pw"><input type="checkbox" data-pw-remember>记住</label>` : ""}
      <button class="btn" data-act="unpack">${s.archive.status === "password" ? "解压" : "解压后逐个归档"}</button></div>` : ""}
    <div class="form">
      <label>项目</label><div class="full combo-host" data-combo="project"></div>
      <label>类型</label><div class="combo-host" data-combo="type"></div>
      <label>日期</label><input class="field" type="date" data-f="doc_date" value="${esc(s.doc_date || "")}">
      <label>标题</label><input class="field" data-f="title" value="${esc(renamed ? curName.replace(/\.[^.]+$/, "") : s.title || "")}" maxlength="40" placeholder="客户简称 + 内容主题">
      <label>版本</label><input class="field mono" data-f="version" placeholder="自动" maxlength="8">
      <label>状态</label><div class="full"><div class="segmented" data-f="status">${statuses.map((x) => `<button type="button" data-v="${x}" class="${x === (s.status || "正式") ? "on" : ""}">${x}</button>`).join("")}</div></div>
    </div>
    <input type="hidden" data-f="project_id" value="${esc(s.project_id || "")}"><input type="hidden" data-f="doc_type" value="${esc(s.doc_type || "")}">
    <div class="preview-name" data-preview>…</div>
    <div class="card-foot">
      <label class="remember">${ic("sparkles")}记住规则：文件名包含 <input class="field" data-remember placeholder="例如 ERP门户"> 时归入此项目</label>
      <div class="spacer"></div>
      <button class="btn" data-act="dismiss" title="不再处理这个文件，文件本身保留">移出列表</button>
      <button class="btn" data-act="rerun" ${j.missing ? "disabled" : ""}>${ic("refresh")}重新识别</button>
      <button class="btn primary" data-act="ok" ${j.missing ? "disabled" : ""}>${ic("check")}归档</button>
    </div>`;
  $(".thumb", el)?.addEventListener("error", (e) => { e.target.outerHTML = docIcon(curName); }, { once: true });
  makeCombo($('[data-combo="project"]', el), $('[data-f="project_id"]', el), { options: projectChoices(s.candidates || []), placeholder: "请选择项目…", minWidth: 440 });
  mountTypeCombo($('[data-combo="type"]', el), $('[data-f="doc_type"]', el));
  const get = () => {
    const v = (k) => $(`[data-f="${k}"]`, el)?.value || "";
    return {
      project_id: v("project_id") ? Number(v("project_id")) : null, doc_type: v("doc_type"), title: v("title"),
      doc_date: v("doc_date"), version: v("version").trim(), status: $(`[data-f="status"] .on`, el)?.dataset.v || "正式",
    };
  };
  let timer;
  const preview = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const f = get();
      const box = $("[data-preview]", el);
      if (!f.project_id) { box.innerHTML = `<span class="path">选择项目后显示归档名称</span>`; return; }
      try {
        const r = await api("/api/preview-name", { json: { ...f, ext: "." + extOf(j.original_name) } });
        box.innerHTML = `<span class="path">${esc(r.path)}</span><br>${esc(r.name)} <span class="${r.valid ? "ok" : "bad"}">${r.valid ? "✓ 符合命名规范" : "✗ 不符合命名规范"}</span>`;
        if (r.version && !$('[data-f="version"]', el).value) $('[data-f="version"]', el).placeholder = `自动（${r.version}）`;
      } catch (e) { box.textContent = e.message; }
    }, 220);
  };
  $$("[data-f]", el).forEach((x) => { x.addEventListener("input", preview); x.addEventListener("change", preview); });
  $$('[data-f="status"] button', el).forEach((b) => (b.onclick = () => { $$('[data-f="status"] button', el).forEach((x) => x.classList.remove("on")); b.classList.add("on"); preview(); }));
  const confirm = async () => {
    const f = get();
    if (!f.project_id) return toast("请选择项目", j.original_name, "error");
    const btn = $('[data-act="ok"]', el);
    btn.disabled = true;
    try {
      const r = await api(`/api/jobs/${j.id}/confirm`, { json: { ...f, remember: $("[data-remember]", el).value.trim() } });
      removeCard(el);
      toast("已归档", r.job?.result?.name || "");
      (r.learned || []).forEach((x, k) => setTimeout(() => toast("学会了一条新规则", x.text), 400 + k * 300));
      (r.disabled || []).forEach((x, k) => setTimeout(() => toast("已停用一条自动规则", `「${x.pattern}」与这次的人工确认不一致`), 700 + k * 300));
      S.sig = ""; tick();
    } catch (e) { btn.disabled = false; fail(e); }
  };
  $('[data-act="ok"]', el).onclick = confirm;
  $('[data-act="rerun"]', el).onclick = async () => { try { await api(`/api/jobs/${j.id}/rerun`, { method: "POST" }); toast("已提交重新识别", curName); } catch (e) { fail(e); } };
  $('[data-act="dismiss"]', el).onclick = () => dismissJob(j, el);
  const unpackBtn = $('[data-act="unpack"]', el);
  if (unpackBtn) {
    const doUnpack = async () => {
      const pw = $("[data-pw]", el);
      if (pw && !pw.value) { pw.focus(); return; }
      unpackBtn.disabled = true;
      try {
        const r = await api(`/api/jobs/${j.id}/unpack`, { json: { password: pw?.value || "", remember: !!$("[data-pw-remember]", el)?.checked } });
        toast(`已解压 ${r.count} 个文件`, "正在逐个识别归档…");
        removeCard(el); S.sig = ""; tick();
      } catch (e) { unpackBtn.disabled = false; fail(e); pw?.select(); }
    };
    unpackBtn.onclick = doUnpack;
    $("[data-pw]", el)?.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); e.stopPropagation(); doUnpack(); } });
  }
  $$('[data-act="ql"]', el).forEach((b) => (b.onclick = () => openPath(j.staged_path, "quicklook")));
  $('[data-act="reveal"]', el).onclick = () => openPath(j.staged_path, "reveal");
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing && !["TEXTAREA", "BUTTON"].includes(e.target.tagName) && !e.target.closest("[data-remember]")) { e.preventDefault(); confirm(); }
  });
  el.addEventListener("focusin", () => { $$(".card.focus").forEach((x) => x.classList.remove("focus")); });
  preview();
  return el;
}

/* ---------------------------------------------------------------- 处理记录 */
async function renderActivity() {
  toolbar("处理记录", "每一次自动或人工操作都可追溯、可撤销");
  const filters = [["", "全部"], ["archived", "已归档"], ["pending_review", "待复核"], ["unmatched,error", "未匹配"], ["unpacked", "已解压"], ["duplicate,skipped", "重复"], ["ignored", "已忽略"]];
  if (!$("#act-list")) {
    content.innerHTML = `<div class="page"><div class="review-head"><div class="segmented" id="act-tabs">${filters.map(([k, v]) => `<button data-k="${k}">${v}</button>`).join("")}</div></div><div class="group" id="act-list"></div></div>`;
    $$("#act-tabs button").forEach((b) => (b.onclick = () => { S.activityFilter = b.dataset.k; renderActivity(); }));
  }
  $$("#act-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.k === S.activityFilter));
  try {
    const jobs = await api(`/api/jobs?limit=300${S.activityFilter ? `&status=${S.activityFilter}` : ""}`);
    const box = $("#act-list");
    if (!box) return;
    box.innerHTML = jobs.length ? jobs.map(jobRow).join("") : `<div class="empty">${ic("activity")}<h3>暂无记录</h3></div>`;
    bindJobRows(box);
  } catch (e) { fail(e); }
}

/* ---------------------------------------------------------------- 归档库（分栏） */
async function renderLibrary(target) {
  toolbar("归档库", "", `<button class="btn" id="tb-reveal-root">${ic("folder")}在${FM()}中打开</button><button class="btn icon" id="tb-lib-refresh" title="刷新">${ic("refresh")}</button>`);
  $("#tb-reveal-root").onclick = () => openPath(S.st?.root || "", "open");
  $("#tb-lib-refresh").onclick = () => navigateTo(currentPath());
  content.className = "content";
  content.innerHTML = `<div class="page wide lib"><div id="lib-banner"></div><div class="browser"><div class="columns" id="cols" tabindex="0"></div><aside class="inspector" id="insp"></aside></div></div>`;
  $("#cols").addEventListener("keydown", colsKey);
  await navigateTo(target || currentPath() || "");
  libBanner();
}
async function libBanner() {
  const r = await api("/api/tidy?quick=1").catch(() => null);
  const box = $("#lib-banner");
  if (!box || !r) return;
  const n = r.groups.length;
  box.innerHTML = n ? `<div class="lib-banner">${ic("warning")}<span class="grow">有 ${n} 个客户的文件分散在多个文件夹里（多半是换过数据库，或同一客户名称写法不同）。</span><button class="btn" id="lib-tidy">${ic("merge")}整理…</button></div>` : "";
  $("#lib-tidy")?.addEventListener("click", tidySheet);
}
function currentPath() {
  const last = S.cols[S.cols.length - 1];
  if (!last) return "";
  return last.sel ? last.sel : last.path;
}
async function loadCol(i, path) {
  const data = await api(`/api/browse?path=${encodeURIComponent(path)}`);
  S.cols = S.cols.slice(0, i);
  S.cols[i] = { path, entries: data.entries, sel: null };
}
async function navigateTo(path) {
  S.cols = [];
  try {
    await loadCol(0, "");
    const parts = (path || "").split("/").filter(Boolean);
    let acc = "";
    for (let k = 0; k < parts.length; k++) {
      acc = acc ? `${acc}/${parts[k]}` : parts[k];
      const col = S.cols[k];
      const ent = col.entries.find((e) => e.path === acc);
      if (!ent) break;
      col.sel = acc;
      if (ent.dir) await loadCol(k + 1, acc);
      else break;
    }
  } catch (e) { fail(e); }
  let f = -1;
  S.cols.forEach((c, i) => { if (c.sel) f = i; });
  S.colFocus = Math.max(0, f);
  drawCols();
}
function drawCols() {
  const box = $("#cols");
  if (!box) return;
  box.innerHTML = S.cols.map((c, i) => {
    let lastSystem = false;
    const items = c.entries.map((e) => {
      let sep = "";
      if (e.system && !lastSystem && i === 0) { sep = `<div class="col-sep"></div>`; }
      lastSystem = e.system;
      const sel = c.sel === e.path;
      return `${sep}<div class="col-item ${e.system ? "system" : ""} ${sel ? "sel" : ""} ${sel && i === S.colFocus ? "active" : ""}" data-i="${i}" data-p="${esc(e.path)}" title="${esc(e.name)}">
        ${e.dir ? folderIcon(e.system) : docIcon(e.name, "sm")}<span class="nm">${esc(e.display ? `${e.display}` : e.name)}</span>
        ${e.dir ? `<span class="cnt">${e.count || ""}</span>${ic("chevron", "chev")}` : e.version ? `<span class="cnt">${esc(e.version)}</span>` : ""}</div>`;
    }).join("");
    return `<div class="col">${items || `<div class="col-item system"><span class="nm">空文件夹</span></div>`}</div>`;
  }).join("");
  $$(".col-item[data-p]", box).forEach((it) => it.addEventListener("click", () => selectItem(Number(it.dataset.i), it.dataset.p)));
  $$(".col-item[data-p]", box).forEach((it) => it.addEventListener("dblclick", () => {
    const e = findEntry(Number(it.dataset.i), it.dataset.p);
    if (e && !e.dir) openPath(e.path, "open");
  }));
  box.scrollLeft = box.scrollWidth;
  const last = S.cols[S.colFocus];
  const sel = last && last.sel && findEntry(S.colFocus, last.sel);
  drawInspector(sel || null);
  const parts = currentPath().split("/").filter(Boolean);
  $("#tb-sub").innerHTML = `<span class="pathbar">${["归档库", ...parts].map((p) => `<span>${esc(p)}</span>`).join(ic("chevron"))}</span>`;
}
function findEntry(i, path) { return S.cols[i]?.entries.find((e) => e.path === path); }
async function selectItem(i, path) {
  const e = findEntry(i, path);
  if (!e) return;
  S.cols = S.cols.slice(0, i + 1);
  S.cols[i].sel = path;
  S.colFocus = i;
  if (e.dir) {
    try { await loadCol(i + 1, path); } catch (err) { fail(err); }
  }
  drawCols();
  $("#cols").focus({ preventScroll: true });
}
function colsKey(e) {
  const i = S.colFocus;
  const col = S.cols[i];
  if (!col) return;
  const idx = col.entries.findIndex((x) => x.path === col.sel);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const n = Math.min(col.entries.length - 1, Math.max(0, idx + (e.key === "ArrowDown" ? 1 : -1)));
    if (col.entries[n]) selectItem(i, col.entries[n].path);
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    const next = S.cols[i + 1];
    if (next && next.entries.length) selectItem(i + 1, next.entries[0].path);
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    if (i > 0) { S.cols = S.cols.slice(0, i + 1); S.cols[i].sel = null; S.colFocus = i - 1; drawCols(); }
  } else if (e.key === " ") {
    e.preventDefault();
    const ent = col.sel && findEntry(i, col.sel);
    if (ent && !ent.dir) openPath(ent.path, "quicklook");
  } else if (e.key === "Enter") {
    const ent = col.sel && findEntry(i, col.sel);
    if (ent && !ent.dir) openPath(ent.path, "open");
  }
}
async function drawInspector(e) {
  const box = $("#insp");
  if (!box) return;
  if (!e) {
    const st = S.st;
    box.innerHTML = `<div class="big">${folderIcon()}<div class="nm">归档库</div><div class="kind selectable">${esc(st?.root || "")}</div></div>
      <dl class="kv"><dt>客户</dt><dd>${S.cols[0]?.entries.filter((x) => x.kind === "customer").length || 0} 个</dd><dt>在建项目</dt><dd>${st?.counts.projects || 0} 个</dd><dt>归档文件</dt><dd>${st?.counts.files || 0} 个</dd></dl>
      <p class="note">用方向键浏览，空格键快速查看，回车打开文件。</p>`;
    $(".big .folder-ico", box).style.cssText = "width:72px;height:60px";
    return;
  }
  if (e.dir) {
    const stray = !e.kind && !e.system && !e.path.includes("/");
    box.innerHTML = `<div class="big">${folderIcon(e.system)}<div class="nm selectable">${esc(e.name)}</div><div class="kind">${e.kind === "customer" ? "客户" : e.kind === "project" ? "项目" : e.system ? "系统文件夹" : "文件夹"} · ${e.count || 0} 项</div></div>
      <div class="btns"><button class="btn" data-o="open">${ic("open")}打开</button><button class="btn" data-o="reveal">${ic("folder")}在${FM()}中显示</button></div>
      ${stray ? `<p class="note">这个文件夹没有对应的客户，常见于换过数据库后留下的旧客户文件夹。可以把它并入现在的客户，里面的文件会按项目放回正式目录。</p><div class="btns"><button class="btn" id="insp-tidy">${ic("merge")}整理重复客户…</button></div>` : ""}`;
    $(".big .folder-ico", box).style.cssText = "width:72px;height:60px";
    $$("[data-o]", box).forEach((b) => (b.onclick = () => openPath(e.path, b.dataset.o)));
    $("#insp-tidy")?.addEventListener("click", tidySheet);
    return;
  }
  box.innerHTML = `<div class="big">${docIcon(e.name, "lg")}<div class="nm selectable">${esc(e.name)}</div></div><div class="processing" style="justify-content:center"><span class="spinner"></span></div>`;
  let d;
  try { d = await api(`/api/file?path=${encodeURIComponent(e.path)}`); } catch (err) { box.innerHTML = `<p class="note">${esc(err.message)}</p>`; return; }
  const r = d.record || {};
  const kind = (d.type_name ? d.type_name + " · " : "") + (extOf(e.name).toUpperCase() || "文件");
  box.innerHTML = `<div class="big">${docIcon(e.name, "lg")}<div class="nm selectable">${esc(d.name)}</div><div class="kind">${esc(kind)}</div>
      <div class="btns"><button class="btn" data-o="open">${ic("open")}打开</button><button class="btn" data-o="quicklook">${ic("eye")}快速查看</button><button class="btn" data-o="reveal">${ic("folder")}显示</button></div></div>
    <dl class="kv">
      ${d.project ? `<dt>项目</dt><dd>${esc(d.project.project_no)}<br>${esc(d.project.label)}</dd>` : ""}
      ${r.doc_type ? `<dt>类型码</dt><dd><span class="typecode">${esc(r.doc_type)}</span></dd>` : ""}
      ${r.version ? `<dt>版本</dt><dd>${esc(r.version)} · ${esc(r.status || "")}</dd>` : ""}
      ${r.doc_date ? `<dt>内容日期</dt><dd>${esc(r.doc_date)}</dd>` : ""}
      <dt>大小</dt><dd>${fmtSize(d.size)}</dd>
      <dt>修改时间</dt><dd>${fmtTime(d.mtime)}</dd>
      ${r.original_name ? `<dt>原始文件名</dt><dd class="selectable">${esc(r.original_name)}</dd>` : ""}
      ${d.job ? `<dt>处理方式</dt><dd>${esc(d.job.method || "")} · ${esc(d.job.source || "")}</dd>` : ""}
      ${r.sensitivity === "高" ? `<dt>敏感级别</dt><dd><span class="tag red">高</span></dd>` : ""}
    </dl>
    ${r.summary ? `<h4>摘要</h4><div class="selectable" style="font-size:12px">${esc(r.summary)}</div>` : ""}
    ${d.versions.length > 1 ? `<h4>版本历史</h4>${d.versions.map((v) => `<div class="ver">${docIcon(v.archive_name, "sm")}<span class="v">${esc(v.version)}</span><span>${esc(v.status)}</span><span class="t">${v.state === "superseded" ? "历史版本" : "当前"}</span><button class="btn plain icon" data-ql="${esc(v.archive_path)}" title="快速查看">${ic("eye")}</button></div>`).join("")}` : ""}
    <h4>对外交付名</h4><div style="display:flex;gap:6px;align-items:center"><span class="selectable" style="font-size:12px;word-break:break-all;flex:1">${esc(d.external_name)}</span><button class="btn icon" id="copy-ext" title="复制">${ic("copy")}</button></div>`;
  $$("[data-o]", box).forEach((b) => (b.onclick = () => openPath(e.path, b.dataset.o)));
  $$("[data-ql]", box).forEach((b) => (b.onclick = () => openPath(b.dataset.ql, "quicklook")));
  $("#copy-ext").onclick = async () => { try { await navigator.clipboard.writeText(d.external_name); toast("已复制对外交付名", d.external_name); } catch (err) { fail(err); } };
}

/* ---------------------------------------------------------------- 项目 */
async function renderProjects() {
  toolbar("项目", "客户与项目来自 CRM，决定归档目录结构",
    `<button class="btn" id="tb-tidy" title="合并同一客户的多个文件夹">${ic("merge")}整理重复客户</button><button class="btn" id="tb-import">${ic("import")}导入 Excel/CSV…</button><button class="btn" id="tb-tpl">下载模板</button><button class="btn primary" id="tb-new">${ic("plus")}新建项目</button>`);
  $("#tb-tidy").onclick = tidySheet;
  $("#tb-new").onclick = () => projectSheet(null);
  $("#tb-tpl").onclick = () => { location.href = "/api/projects/template.csv"; };
  $("#tb-import").onclick = () => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = ".csv,.xlsx,.xlsm";
    inp.onchange = async () => {
      const fd = new FormData(); fd.append("file", inp.files[0]);
      try {
        const r = await api("/api/projects/import", { method: "POST", body: fd });
        toast("导入完成", `新增 ${r.created} 个，更新 ${r.updated} 个${r.adopted ? `；接上了 ${r.adopted} 个以前的项目文件夹${r.registered ? `，补登记 ${r.registered} 个文件` : ""}` : ""}${r.errors.length ? `，${r.errors.length} 行有问题` : ""}`);
        if (r.errors.length) setTimeout(() => toast("以下行未导入", r.errors.slice(0, 3).join("；"), "error"), 400);
        await refreshMeta(); renderProjects();
      } catch (e) { fail(e); }
    };
    inp.click();
  };
  await refreshMeta();
  const rules = await api("/api/rules").catch(() => []);
  S.pjFilter = S.pjFilter || "";
  S.pjStatus = S.pjStatus || "";
  content.innerHTML = `<div class="page wide-page">
    ${S.projects.length ? `<div class="list-head">
      <label class="search filter">${ic("search")}<input id="pj-filter" placeholder="筛选：编号、客户、项目、业务线，支持拼音首字母" value="${esc(S.pjFilter)}" autocomplete="off"></label>
      <div class="segmented" id="pj-status">${[["", "全部"], ["进行中", "进行中"], ["已结项", "已结项"]].map(([k, v]) => `<button data-k="${k}">${v}</button>`).join("")}</div>
      <span class="count" id="pj-count"></span></div>` : ""}
    <div class="group table-wrap" id="pj-table">${S.projects.length ? "" : `<div class="empty">${ic("briefcase")}<h3>还没有项目</h3>从 CRM 导出项目列表（Excel 或 CSV）后导入，或手动新建<div style="margin-top:12px;display:flex;gap:8px;justify-content:center"><button class="btn" onclick="$('#tb-import').click()">导入…</button><button class="btn primary" onclick="projectSheet(null)">新建项目</button></div></div>`}</div>
    <p class="note"><b>点击任意一行即可编辑项目。</b>CRM 同步目前通过导入 CRM 导出的 Excel/CSV，同一项目编号再次导入会更新而不是重复创建。每个项目自动生成 <span class="mono">00_项目管理 … 06_客户资料</span> 等标准阶段目录。客户别名（如「澄湾」「CW」）能显著提升识别准确率。</p>
    <div class="group-title">已学会的规则<span class="more desc" style="color:var(--secondary)">${rules.filter((r) => r.enabled).length} 条生效</span></div>
    <div class="group">${rules.length ? rules.map((r) => `<div class="row ${r.enabled ? "" : "muted"}"><span class="typecode">${ic(r.source === "auto" ? "sparkles" : "person")}</span>
      <div class="grow"><div class="selectable">${esc(r.text)}</div><div class="desc">${r.source === "auto" ? "自动学习" : "手动添加"} · ${r.kind === "type" ? "判断类型" : "判断项目"} · 命中 ${r.hits} 次${r.enabled ? "" : " · 已停用"}</div></div>
      <button class="btn plain" data-toggle="${r.id}" data-on="${r.enabled ? 0 : 1}">${r.enabled ? "停用" : "启用"}</button><button class="btn plain danger" data-delrule="${r.id}">删除</button></div>`).join("")
      : `<div class="row"><span class="desc">人工确认文件时，同一个特征词（如系统名称、你们常用的报告叫法）出现两次且结论一致，系统会自动学会一条规则；也可以在确认时填写「记住规则」。</span></div>`}</div>
  </div>`;
  $$("[data-delrule]").forEach((b) => (b.onclick = async () => { await api(`/api/rules/${b.dataset.delrule}`, { method: "DELETE" }).catch(fail); renderProjects(); }));
  $$("[data-toggle]").forEach((b) => (b.onclick = async () => { await api(`/api/rules/${b.dataset.toggle}`, { method: "PUT", json: { enabled: b.dataset.on === "1" } }).catch(fail); renderProjects(); }));
  if (!S.projects.length) return;

  const draw = () => {
    const q = S.pjFilter.trim();
    let list = S.projects.filter((p) => !S.pjStatus || (p.status === "已结项" ? "已结项" : "进行中") === S.pjStatus);
    if (q) {
      list = list.map((p) => {
        p._f = p._f || [p.short_name, p.customer_short, p.project_no, p.name, p.customer_full || "", (p.aliases || []).join(" "), p.biz_line || ""].map(fzPrep);
        return { p, m: fzMatch(q, p._f) };
      }).filter((x) => x.m).sort((a, b) => b.m.score - a.m.score).map((x) => x.p);
    }
    const hl = (s) => (q ? fzHighlight(s || "", q) : esc(s || ""));
    $$("#pj-status button").forEach((b) => b.classList.toggle("on", b.dataset.k === S.pjStatus));
    $("#pj-count").textContent = list.length === S.projects.length ? `共 ${list.length} 个项目` : `${list.length} / ${S.projects.length} 个项目`;
    const rows = list.map((p) => `<tr class="click" data-id="${p.id}" title="点击编辑">
      <td class="mono nowrap" title="${esc(p.project_no)}">${hl(p.project_no)}</td>
      <td><div class="clip"><b>${hl(p.customer_short)}</b></div><div class="clip sub" title="${esc(p.customer_full || "")}">${hl(p.customer_full)}${p.aliases?.length ? ` · 别名：${hl(p.aliases.join("、"))}` : ""}</div></td>
      <td><div class="clip" title="${esc(p.short_name)}">${hl(p.short_name)}</div><div class="clip sub" title="${esc(p.name)}">${hl(p.name)}</div></td>
      <td>${p.biz_line ? `<span class="tag clip-tag" title="${esc(p.biz_line)}">${hl(p.biz_line)}</span>` : `<span class="sub">—</span>`}</td>
      <td>${p.status === "已结项" ? `<span class="tag">已结项</span>` : `<span class="tag green">进行中</span>`}</td>
      <td class="num">${p.file_count}</td>
      <td class="row-acts"><button class="btn" data-edit="${p.id}">编辑</button><button class="btn plain icon" title="在${FM()}中打开项目目录" data-dir="${esc(p.customer_dir + "/" + p.dir_name)}">${ic("folder")}</button><button class="btn plain icon" title="生成归档包" data-pack="${p.id}">${ic("archive")}</button></td></tr>`).join("");
    $("#pj-table").innerHTML = `<table class="table fixed">
      <colgroup><col style="width:186px"><col style="width:27%"><col><col style="width:118px"><col style="width:74px"><col style="width:48px"><col style="width:136px"></colgroup>
      <thead><tr><th>项目编号</th><th>客户</th><th>项目</th><th>业务线</th><th>状态</th><th class="num">文件</th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="7"><div class="empty" style="padding:28px">没有符合条件的项目</div></td></tr>`}</tbody></table>`;
  };
  draw();
  $("#pj-filter").addEventListener("input", (e) => { S.pjFilter = e.target.value; draw(); });
  $("#pj-filter").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.target.value = ""; S.pjFilter = ""; draw(); } });
  $$("#pj-status button").forEach((b) => (b.onclick = () => { S.pjStatus = b.dataset.k; draw(); }));
  $("#pj-table").addEventListener("click", async (e) => {
    const find = (id) => S.projects.find((p) => p.id === Number(id));
    const btn = e.target.closest("button");
    if (btn?.dataset.dir) return openPath(btn.dataset.dir, "open");
    if (btn?.dataset.pack) {
      btn.disabled = true;
      try { const r = await api(`/api/projects/${btn.dataset.pack}/package`, { method: "POST" }); toast("归档包已生成", `${r.name}（${r.files} 个文件）`); openPath(r.path, "reveal"); }
      catch (err) { fail(err); } finally { btn.disabled = false; }
      return;
    }
    const tr = e.target.closest("tr[data-id]");
    if (btn?.dataset.edit || (tr && !btn)) {
      if (window.getSelection()?.toString()) return;
      const p = find(btn?.dataset.edit || tr.dataset.id);
      if (p) projectSheet(p);
    }
  });
}

function sheet(html, onOk, okText = "存储") {
  const bd = document.createElement("div");
  bd.className = "sheet-backdrop";
  bd.innerHTML = `<div class="sheet" role="dialog">${html}<div class="foot"><button class="btn" data-x>取消</button><button class="btn primary" data-ok>${esc(okText)}</button></div></div>`;
  document.body.appendChild(bd);
  const close = () => bd.remove();
  $("[data-x]", bd).onclick = close;
  bd.addEventListener("mousedown", (e) => { if (e.target === bd) close(); });
  bd.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); if (e.key === "Enter" && !e.isComposing && e.target.tagName !== "TEXTAREA") { e.preventDefault(); $("[data-ok]", bd).click(); } });
  $("[data-ok]", bd).onclick = async () => {
    const btn = $("[data-ok]", bd);
    btn.disabled = true;
    try { if ((await onOk(bd)) !== false) close(); } catch (e) { fail(e); } finally { btn.disabled = false; }
  };
  setTimeout(() => ($("input, select", bd) || $("[data-ok]", bd))?.focus(), 30);
  return bd;
}

function projectSheet(p) {
  const bizs = [...new Set([...S.projects.map((x) => x.biz_line).filter(Boolean), ...(S.std?.biz_lines || [])])];
  const custList = [...new Map(S.projects.map((x) => [x.customer_id, x])).values()];
  const html = `<h2>${p ? "编辑项目" : "新建项目"}</h2><p class="intro">保存后自动生成「客户 / 项目 / 阶段」三级目录；修改简称会同步重命名目录。</p>
  <div class="body"><div class="grid">
    <label>项目编号</label><input class="field mono" name="project_no" value="${esc(p?.project_no || "")}" placeholder="与 CRM 一致，如 PRJ-2026-0123">
    <label>项目名称</label><input class="field" name="name" value="${esc(p?.name || "")}" placeholder="CRM 中的项目全称">
    <label>项目简称</label><input class="field" name="short_name" value="${esc(p?.short_name || "")}" placeholder="留空自动生成，≤ 20 字">
    <label>业务线</label><input class="field" name="biz_line" list="biz-list" value="${esc(p?.biz_line || "")}" placeholder="如 渗透测试、等保、漏洞扫描，可直接输入">
    <datalist id="biz-list">${bizs.map((b) => `<option value="${esc(b)}">`).join("")}</datalist>
    ${p ? `<label>归档目录</label><div class="mono selectable" style="font-size:11.5px;color:var(--secondary);word-break:break-all">${esc(p.customer_dir)}/${esc(p.dir_name)}</div>` : ""}
    <label>状态</label><div><div class="segmented" data-status>${["进行中", "已结项"].map((s) => `<button type="button" data-v="${s}" class="${(p?.status || "进行中") === s ? "on" : ""}">${s}</button>`).join("")}</div></div>
    <label>起止日期</label><div style="display:flex;gap:6px"><input class="field" type="date" name="start_date" value="${esc(p?.start_date || "")}" style="flex:1"><input class="field" type="date" name="end_date" value="${esc(p?.end_date || "")}" style="flex:1"></div>
    <label>项目关键词</label><input class="field" name="keywords" value="${esc((p?.keywords || []).join("、"))}" placeholder="系统名称、IP 段等，用顿号分隔">
    <div class="sep"></div>
    <label>客户全称</label><input class="field" name="customer_full" list="cust-list" value="${esc(p?.customer_full || "")}" ${p ? "disabled" : ""} placeholder="如 上海澄湾科技有限公司">
    <label>客户简称</label><input class="field" name="customer_short" value="${esc(p?.customer_short || "")}" ${p ? "disabled" : ""} placeholder="留空自动生成，用于目录与文件名">
    <label>客户别名</label><input class="field" name="customer_aliases" value="${esc((p?.aliases || []).join("、"))}" placeholder="文件里常见的叫法，如 澄湾、CW">
    ${p ? `<span></span><div><button type="button" class="btn plain" data-editcust style="padding:0">修改客户名称…</button></div>` : ""}
  </div><datalist id="cust-list">${custList.map((c) => `<option value="${esc(c.customer_full || c.customer_short)}">`).join("")}</datalist></div>`;
  const bd = sheet(html, async (root) => {
    const v = (n) => $(`[name="${n}"]`, root).value.trim();
    const body = {
      project_no: v("project_no"), name: v("name"), short_name: v("short_name"), biz_line: v("biz_line"),
      status: $("[data-status] .on", root).dataset.v, start_date: v("start_date"), end_date: v("end_date"),
      keywords: v("keywords"), customer_aliases: v("customer_aliases"),
    };
    if (p) body.customer_id = p.customer_id;
    else {
      body.customer_full = v("customer_full"); body.customer_short = v("customer_short");
      const hit = custList.find((c) => c.customer_full === body.customer_full || c.customer_short === body.customer_full
        || (body.customer_short && c.customer_short === body.customer_short));
      if (hit) { body.customer_id = hit.customer_id; }
    }
    if (!body.project_no) throw new Error("请填写项目编号");
    if (!p && !body.customer_id && !body.customer_full && !body.customer_short) throw new Error("请填写客户");
    const r = p ? await api(`/api/projects/${p.id}`, { method: "PUT", json: body }) : await api("/api/projects", { json: body });
    toast(p ? "项目已更新" : "项目已创建", `${r.customer_dir}/${r.dir_name}`);
    await refreshMeta(); renderProjects();
  });
  $$("[data-status] button", bd).forEach((b) => (b.onclick = () => { $$("[data-status] button", bd).forEach((x) => x.classList.remove("on")); b.classList.add("on"); }));
  $("[data-editcust]", bd)?.addEventListener("click", () => { bd.remove(); customerSheet(p); });
}

/* ---------------------------------------------------------------- 整理重复客户 */
const tidySummary = (r) => [r.customers ? `合并客户 ${r.customers} 个` : "", r.folders ? `并入文件夹 ${r.folders} 个` : "",
  r.moved ? `移动文件 ${r.moved} 个` : "", r.duplicates ? `去掉内容完全相同的重复文件 ${r.duplicates} 个` : "",
  r.renamed ? `同名但内容不同的加了编号 ${r.renamed} 个` : "", r.registered ? `补登记 ${r.registered} 个` : ""].filter(Boolean).join("，") || "没有需要移动的文件";

async function tidySheet() {
  let r;
  try { r = await api("/api/tidy"); } catch (e) { return fail(e); }
  if (!r.groups.length && !r.loose.length && !r.unindexed) { toast("没有发现重复的客户", "每个客户都只有一个文件夹"); return; }
  const st = { groups: r.groups.map((g) => ({ target: { ...g.target }, items: g.items.map((i) => ({ ...i })) })), loose: r.loose.map((x) => ({ ...x, into: "" })), reindex: true };
  const files = (n) => (n == null ? "" : `${n} 个文件`);
  const bd = sheet(`<h2>整理重复的客户</h2><p class="intro">把同一个客户的多个文件夹合并成一个，里面的项目文件夹放回各自的正式目录。文件只移动、不删除；两边内容完全相同的只留一份，同名但内容不同的加编号保留。</p><div class="body tidy" id="tidy-body"></div>`, async () => {
    const groups = st.groups.map((g) => ({ target: g.target.id, customers: g.items.filter((i) => i.kind === "customer" && i.checked).map((i) => i.id), folders: g.items.filter((i) => i.kind === "folder" && i.checked).map((i) => i.path) }))
      .filter((g) => g.customers.length || g.folders.length);
    st.loose.forEach((x) => { if (x.into) groups.push({ target: Number(x.into), customers: [], folders: [x.path] }); });
    if (!groups.length && !(st.reindex && r.unindexed)) throw new Error("没有勾选要合并的内容");
    const res = await api("/api/tidy/merge", { json: { groups, reindex: st.reindex } });
    toast("整理完成", tidySummary(res));
    if (res.error_count) setTimeout(() => toast(`${res.error_count} 个文件没能移动`, `${res.errors.slice(0, 2).join("；")}。关掉正在打开的文件后，再点一次整理即可。`, "error"), 400);
    S.std = null; await Promise.all([refreshMeta(), tick()]);
    if (S.route === "library") renderLibrary(); else if (S.route === "projects") renderProjects();
  }, "合并");
  $(".sheet", bd).classList.add("wide-sheet");
  const draw = () => {
    const groupHtml = st.groups.map((g, gi) => `<div class="tidy-group">
      <div class="tidy-target">${folderIcon()}<div class="grow"><div><b>${esc(g.target.name)}</b> <span class="tag blue">保留</span></div>
        <div class="sub">${esc(g.target.dir)} · ${g.target.projects} 个项目${g.target.files ? ` · ${g.target.files} 个文件` : ""}</div></div></div>
      ${g.items.map((it, k) => `<label class="tidy-item"><input type="checkbox" data-g="${gi}" data-k="${k}" ${it.checked ? "checked" : ""}>
        <div class="grow"><div class="nm">${it.kind === "customer" ? `客户「${esc(it.name)}」<span class="sub"> ${esc(it.full || "")}</span>` : `<span class="mono">${esc(it.name)}</span>`}</div>
        <div class="sub">${esc(it.reason)}${it.kind === "customer" ? ` · ${it.projects} 个项目` : ""}${it.files != null ? ` · ${files(it.files)}` : ""}</div></div>
        ${it.kind === "customer" ? `<button type="button" class="btn plain" data-keep="${gi}:${k}">改为保留这个</button>` : ""}</label>`).join("")}
    </div>`).join("");
    const looseHtml = st.loose.length ? `<div class="tidy-group"><div class="tidy-head">没有对应客户的文件夹<span class="sub"> · 可能是你自己放进来的，不处理就保持原样</span></div>
      ${st.loose.map((x, k) => `<div class="tidy-item"><div class="grow"><div class="nm mono">${esc(x.name)}</div><div class="sub">${files(x.files)}</div></div>
        <select class="field" data-loose="${k}"><option value="">不处理</option>${r.customers.map((c) => `<option value="${c.id}" ${String(x.into) === String(c.id) ? "selected" : ""}>并入「${esc(c.name)}」</option>`).join("")}</select></div>`).join("")}</div>` : "";
    $("#tidy-body", bd).innerHTML = (groupHtml || `<p class="note" style="margin:0 0 10px">没有发现同一客户的多个文件夹。</p>`) + looseHtml +
      `<label class="check-line tidy-reindex"><input type="checkbox" id="tidy-reindex" ${st.reindex ? "checked" : ""}>合并后补登记按规范命名、但数据库里没有记录的文件${r.unindexed ? `（现在已有 ${r.unindexed} 个）` : ""}，登记后能搜到，版本号也能接上</label>`;
    $$("[data-g]", bd).forEach((cb) => (cb.onchange = () => { st.groups[cb.dataset.g].items[cb.dataset.k].checked = cb.checked; }));
    $$("[data-loose]", bd).forEach((sel) => (sel.onchange = () => { st.loose[sel.dataset.loose].into = sel.value; }));
    $("#tidy-reindex", bd).onchange = (e) => { st.reindex = e.target.checked; };
    $$("[data-keep]", bd).forEach((b) => (b.onclick = (e) => {
      e.preventDefault();
      const [gi, k] = b.dataset.keep.split(":").map(Number);
      const g = st.groups[gi]; const it = g.items[k]; const t = g.target;
      g.items[k] = { kind: "customer", id: t.id, name: t.name, full: t.full, dir: t.dir, projects: t.projects, files: t.files, reason: "改为并入", checked: true };
      g.target = { id: it.id, name: it.name, full: it.full, dir: it.dir, projects: it.projects, files: it.files };
      draw();
    }));
  };
  draw();
}

function customerSheet(p) {
  sheet(`<h2>修改客户</h2><p class="intro">客户简称变化后，客户目录会同步改名（编码 ${esc(p.customer_code)} 不变）。</p>
    <div class="body"><div class="grid">
    <label>客户全称</label><input class="field" name="full" value="${esc(p.customer_full || "")}">
    <label>客户简称</label><input class="field" name="short" value="${esc(p.customer_short)}">
    <label>客户别名</label><input class="field" name="aliases" value="${esc((p.aliases || []).join("、"))}"></div></div>`,
  async (root) => {
    const v = (n) => $(`[name="${n}"]`, root).value.trim();
    await api(`/api/customers/${p.customer_id}`, { method: "PUT", json: { short_name: v("short"), full_name: v("full"), aliases: v("aliases") } });
    toast("客户已更新");
    await refreshMeta(); renderProjects();
  });
}

/* ---------------------------------------------------------------- 设置 */
async function renderSettings() {
  toolbar("设置", "修改后立即生效");
  let s;
  try { s = await api("/api/settings"); } catch (e) { return fail(e); }
  const pct = (x) => Math.round(x * 100);
  content.innerHTML = `<div class="page" style="max-width:720px">
    <div class="group-title">${ic("folder")}文件夹</div>
    <div class="group">
      <div class="row"><span class="lbl">归档库位置</span><input class="field grow mono" id="st-root" value="${esc(s.archive_root)}"><button class="btn" id="st-pick">选择…</button><button class="btn icon" title="在${FM()}中打开" id="st-open">${ic("open")}</button></div>
      <div class="row"><span class="lbl">收件箱</span><input class="field grow mono" id="st-inbox" value="${esc(s.inbox_dir)}" placeholder="留空 = 归档库下的 _收件箱"><button class="btn" id="st-pick-inbox">选择…</button></div>
      <div class="row"><div class="grow"><div>自动整理</div><div class="desc">监听收件箱，新文件放进来后自动识别、重命名、归档</div></div><label class="switch"><input type="checkbox" id="st-watch" ${s.watch_enabled ? "checked" : ""}><span></span></label></div>
    </div>
    <p class="note">更换归档库位置不会移动已有文件；如需迁移，请先在${FM()}中把整个文件夹移过去，再在这里选择新位置。</p>

    <div class="group-title">${ic("tray")}文件来源<span class="more desc" style="color:var(--secondary)">只复制，不移动、不删除原文件</span></div>
    <div class="group" id="st-sources"><div class="row"><span class="desc">正在读取…</span></div></div>
    <p class="note">只收开启之后新收到的文件，以前的不管。请在微信「设置 → 文件管理」里打开文件自动下载，收到的文件才会自动出现在电脑上；聊天里的图片要「以文件形式」发送才会被收进来（例如手机拍的授权书发到「文件传输助手」时选文件）。</p>

    <div class="group-title">${ic("bolt")}自动归档规则</div>
    <div class="group">
      <div class="row"><div class="grow"><div>自动归档把握</div><div class="desc">综合把握达到该值直接归档，否则进入待复核</div></div><input type="range" id="st-auto" min="70" max="99" value="${pct(s.auto_threshold)}"><span class="val" id="st-auto-v" style="width:40px;text-align:right">${pct(s.auto_threshold)}%</span></div>
      <div class="row"><div class="grow"><div>复核下限</div><div class="desc">项目把握低于该值视为「未匹配」，需要手动指定项目</div></div><input type="range" id="st-review" min="30" max="85" value="${pct(s.review_threshold)}"><span class="val" id="st-review-v" style="width:40px;text-align:right">${pct(s.review_threshold)}%</span></div>
      <div class="row"><div class="grow"><div>候选项目范围</div><div class="desc">已结项的项目在多少天内仍可接收文件</div></div><input class="field" id="st-days" type="number" min="0" max="3650" value="${s.recent_project_days}" style="width:80px"><span class="val">天</span></div>
    </div>

    <div class="group-title">${ic("sparkles")}持续学习</div>
    <div class="group">
      <div class="row"><div class="grow"><div>参考历史归档</div><div class="desc">新文件先和已归档文件比对，相似的（如每周的周报、同一系统的报告）直接沿用上次的项目和类型</div></div><label class="switch"><input type="checkbox" id="st-hist" ${s.history_enabled ? "checked" : ""}><span></span></label></div>
      <div class="row"><div class="grow"><div>自动学习规则</div><div class="desc">文件名里同一个特征词人工确认达到次数且结论一致时，自动生成规则；被人工纠正的自动规则会自动停用</div></div><label class="switch"><input type="checkbox" id="st-learn" ${s.learn_enabled ? "checked" : ""}><span></span></label></div>
      <div class="row"><div class="grow"><div>生成规则所需次数</div><div class="desc">同类文件人工确认几次后生成规则，次数越多越稳妥</div></div><input class="field" id="st-learn-n" type="number" min="2" max="5" value="${s.learn_min_samples}" style="width:70px"><span class="val">次</span></div>
      <div class="row click" onclick="go('projects')"><div class="grow"><div>查看已学会的规则</div><div class="desc">在「项目」页底部，可以停用或删除</div></div>${ic("chevron")}</div>
    </div>

    <div class="group-title">${ic("photo")}图片与扫描件<span class="more desc" style="color:var(--secondary)">本地识别图中文字，不上传</span></div>
    <div class="group">
      <div class="row"><div class="grow"><div>识别图片和扫描件里的文字</div><div class="desc">授权书、验收单的照片或扫描 PDF 按内容命名归档；截图按图中的客户名找项目</div></div><label class="switch"><input type="checkbox" id="st-ocr" ${s.ocr_enabled ? "checked" : ""}><span></span></label></div>
      <div class="row"><div class="grow"><div>扫描版 PDF 识别页数</div><div class="desc">只识别前几页（封面和标题通常在第一页），每页约 1–3 秒</div></div><input class="field" id="st-ocr-pages" type="number" min="1" max="5" value="${s.ocr_pdf_pages}" style="width:70px"><span class="val">页</span></div>
      <div class="row"><span class="desc grow" id="st-ocr-res">${S.st?.ocr?.ready ? esc(S.st.ocr.msg) : `<span style="color:var(--orange)">${esc(S.st?.ocr?.msg || "")}</span>`}</span><button class="btn" data-test="ocr" ${S.st?.ocr?.ready ? "" : "disabled"}>测试识别</button></div>
    </div>

    <div class="group-title">${ic("archive")}压缩包</div>
    <div class="group">
      <div class="row"><div class="grow"><div>自动解压</div><div class="desc">zip、7z、rar、tar 解压后逐个识别归档，同一个包里的文件互相参考归属</div></div><label class="switch"><input type="checkbox" id="st-unpack" ${s.unpack_enabled ? "checked" : ""}><span></span></label></div>
      <div class="row"><div class="grow"><div>整包归档的文件数</div><div class="desc">超过这个数，或者像扫描结果、日志的包，不拆开，整体当一个文件归档（卡片上仍可手动解压）</div></div><input class="field" id="st-unpack-n" type="number" min="5" max="200" value="${s.unpack_max_files}" style="width:70px"><span class="val">个</span></div>
      <div class="row"><div class="grow"><div>保留原压缩包</div><div class="desc">解压后把原压缩包移到归档库的「_原始压缩包」，关闭则直接删除</div></div><label class="switch"><input type="checkbox" id="st-keep-arch" ${s.keep_archives ? "checked" : ""}><span></span></label></div>
      <div class="row"><div class="grow"><div>记住的解压密码</div><div class="desc">遇到加密包先自动试这些密码；在待复核卡片上输入密码时勾选「记住」即可添加</div></div><span class="val">${s.archive_passwords_count} 个</span><button class="btn" id="st-pw-clear" ${s.archive_passwords_count ? "" : "disabled"}>清空</button></div>
    </div>

    <div class="group-title">${ic("sparkles")}Jev · 快速判断<span class="more desc" style="color:var(--secondary)">TypeSafe AI 决策模型：判断项目、类型、状态</span></div>
    <div class="group">
      <div class="row"><span class="lbl">启用 Jev</span><div class="ctl"><label class="switch"><input type="checkbox" id="st-jev-on" ${s.jev_enabled ? "checked" : ""}><span></span></label></div></div>
      <div class="row"><span class="lbl">API Key</span><input class="field grow mono" id="st-jev-key" type="password" value="${esc(s.jev_api_key)}" placeholder="在 console.typesafe.ai 创建"></div>
      <div class="row"><span class="lbl">模型</span><input class="field grow mono" id="st-jev-model" value="${esc(s.jev_model)}"></div>
      <div class="row"><span class="lbl">接口地址</span><input class="field grow mono" id="st-jev-ep" value="${esc(s.jev_endpoint)}"></div>
      <div class="row"><span class="desc grow" id="st-jev-res">关键词判断不出来或有冲突时才调用，单次约 0.1–0.5 秒</span><button class="btn" data-test="jev">测试连接</button></div>
    </div>

    <div class="group-title">${ic("docs")}DeepSeek · 内容分析<span class="more desc" style="color:var(--secondary)">读正文，生成标题、内容日期和摘要</span></div>
    <div class="group">
      <div class="row"><span class="lbl">启用 DeepSeek</span><div class="ctl"><label class="switch"><input type="checkbox" id="st-ds-on" ${s.deepseek_enabled ? "checked" : ""}><span></span></label></div></div>
      <div class="row"><span class="lbl">API Key</span><input class="field grow mono" id="st-ds-key" type="password" value="${esc(s.deepseek_api_key)}" placeholder="在 platform.deepseek.com 创建"></div>
      <div class="row"><span class="lbl">模型</span><select class="field" id="st-ds-model" style="width:220px">${["deepseek-v4-flash", "deepseek-v4-pro"].map((m) => `<option ${s.deepseek_model === m ? "selected" : ""}>${m}</option>`).join("")}${["deepseek-v4-flash", "deepseek-v4-pro"].includes(s.deepseek_model) ? "" : `<option selected>${esc(s.deepseek_model)}</option>`}</select><span class="desc">flash 快且便宜，适合取标题</span></div>
      <div class="row"><span class="lbl">接口地址</span><input class="field grow mono" id="st-ds-base" value="${esc(s.deepseek_base_url)}"></div>
      <div class="row"><span class="lbl">发送正文长度</span><input class="field" id="st-chars" type="number" min="200" max="6000" step="100" value="${s.text_chars_for_ai}" style="width:90px"><span class="desc">字（只发文件名与正文开头，不上传原文件）</span></div>
      <div class="row"><span class="desc grow" id="st-ds-res">没有配置时，标题取自文件名或文档封面</span><button class="btn" data-test="deepseek">测试连接</button></div>
    </div>

    <div class="group-title">${ic("docs")}命名规范</div>
    <div class="group">
      <div class="row"><span class="lbl">文件命名公式</span><span class="grow mono selectable" style="font-size:12px">${esc(S.std?.formula || "")}</span></div>
      <div class="row"><span class="lbl">示例</span><span class="grow mono selectable" style="font-size:12px;word-break:break-all">PRJ-2026-0123_RPT-DJ_澄湾科技等保测评报告_V1.1_正式_20261016.docx</span></div>
      <div class="row"><span class="lbl">版本规则</span><span class="grow desc" style="font-size:12.5px">草稿/内审/送审 为 V0.x；首次正式交付 V1.0；之后每次修改 V1.1、V1.2…；旧版本自动移入「_历史版本」</span></div>
      <div class="row"><span class="lbl">交付物类型</span><span class="grow desc">${(S.std?.types || []).filter((t) => t.enabled !== false).length} 个在用${(S.std?.types || []).some((t) => !t.builtin) ? `（自定义 ${(S.std?.types || []).filter((t) => !t.builtin).length} 个）` : ""}</span><button class="btn" id="st-type-add">${ic("plus")}新增类型</button><button class="btn" id="st-types-toggle">查看全部</button></div>
      <div id="st-types" class="${S.typesOpen ? "" : "hidden"}"><table class="table fixed types-table"><colgroup><col style="width:112px"><col style="width:150px"><col style="width:96px"><col><col style="width:64px"></colgroup><thead><tr><th>类型码</th><th>名称</th><th>归档目录</th><th>识别关键词</th><th></th></tr></thead><tbody>${[...(S.std?.types || [])].sort((a, b) => (a.builtin === b.builtin ? 0 : a.builtin ? 1 : -1)).map((t) => `<tr class="click ${t.enabled === false ? "muted" : ""}" data-type="${esc(t.code)}"><td class="typecode nowrap">${esc(t.code)}</td><td><div class="clip" title="${esc(t.name)}">${esc(t.name)}</div>${t.builtin ? "" : `<span class="tag blue">自定义</span>`}${t.enabled === false ? ` <span class="tag">已停用</span>` : ""}</td><td class="nowrap" title="${esc(t.stage)}">${esc(t.stage.replace("03_过程文档/证据", "03_证据"))}</td><td class="ellipsis" style="color:var(--secondary)" title="${esc(t.keywords.join("、"))}">${esc(t.keywords.join("、"))}</td><td style="text-align:right;color:var(--accent);white-space:nowrap">${t.builtin ? "加词" : "编辑"}</td></tr>`).join("")}</tbody></table></div>
    </div>
    <div class="group-title">${ic("gear")}运行方式</div>
    <div class="group" id="st-system">
      ${isWin() ? `
      <div class="row"><div class="grow"><div>开机自动运行</div><div class="desc">登录 Windows 后在后台运行，右下角托盘有图标，不用开着命令行窗口</div></div><label class="switch"><input type="checkbox" id="st-autostart"><span></span></label></div>
      <div class="row"><div class="grow"><div>右键「发送到 → 文渊」</div><div class="desc">在资源管理器里选中文件或文件夹，右键 → 发送到 → 文渊</div></div><label class="switch"><input type="checkbox" id="st-sendto" ${s.sendto_enabled ? "checked" : ""}><span></span></label></div>
      <div class="row"><div class="grow"><div>发送后原文件</div><div class="desc">选「移走」相当于把文件拖进收件箱，桌面和下载文件夹会变干净</div></div><div class="segmented" id="st-sendto-move"><button data-v="0" class="${s.sendto_move ? "" : "on"}">保留（复制）</button><button data-v="1" class="${s.sendto_move ? "on" : ""}">移走</button></div></div>
      <div class="row"><div class="grow"><div>处理完成后通知</div><div class="desc">右下角弹出「自动归档了 3 个文件，2 个需要复核」</div></div><label class="switch"><input type="checkbox" id="st-notify" ${s.notify_enabled ? "checked" : ""}><span></span></label></div>`
      : `<div class="row"><div class="grow"><div>开机自动运行</div><div class="desc">双击程序文件夹里的「设置开机自动运行.command」；取消用「取消开机自动运行.command」</div></div></div>`}
      <div class="row"><div class="grow"><div>退出文渊</div><div class="desc">关闭后台服务；再次使用时双击「启动文渊」${isWin() ? "或从开始菜单打开" : ""}</div></div><button class="btn" id="st-quit">退出</button></div>
    </div>
    <p class="note">文渊 ${esc(S.st?.version || "")} · 数据与设置保存在程序目录的 data 文件夹 · 服务只监听本机 127.0.0.1</p>
  </div>`;

  const save = async (changes, msg) => {
    try { await api("/api/settings", { json: changes }); if (msg) toast(msg); S.sig = ""; tick(); } catch (e) { fail(e); }
  };
  const bindText = (id, key, msg) => $(id).addEventListener("change", (e) => save({ [key]: e.target.value.trim() }, msg));
  bindText("#st-root", "archive_root", "归档库位置已更新");
  bindText("#st-inbox", "inbox_dir", "收件箱已更新");
  bindText("#st-jev-key", "jev_api_key", "Jev API Key 已保存");
  bindText("#st-jev-model", "jev_model");
  bindText("#st-jev-ep", "jev_endpoint");
  bindText("#st-ds-key", "deepseek_api_key", "DeepSeek API Key 已保存");
  bindText("#st-ds-model", "deepseek_model");
  bindText("#st-ds-base", "deepseek_base_url");
  $("#st-days").addEventListener("change", (e) => save({ recent_project_days: Number(e.target.value) }));
  $("#st-hist").addEventListener("change", (e) => save({ history_enabled: e.target.checked }, e.target.checked ? "已开启参考历史归档" : "已关闭参考历史归档"));
  $("#st-learn").addEventListener("change", (e) => save({ learn_enabled: e.target.checked }, e.target.checked ? "已开启自动学习规则" : "已关闭自动学习规则"));
  $("#st-learn-n").addEventListener("change", (e) => save({ learn_min_samples: Math.max(2, Math.min(5, Number(e.target.value) || 2)) }));
  $("#st-chars").addEventListener("change", (e) => save({ text_chars_for_ai: Number(e.target.value) }));
  $("#st-unpack").addEventListener("change", (e) => save({ unpack_enabled: e.target.checked }, e.target.checked ? "已开启自动解压" : "已关闭自动解压"));
  $("#st-unpack-n").addEventListener("change", (e) => save({ unpack_max_files: Math.max(5, Math.min(200, Number(e.target.value) || 30)) }));
  $("#st-keep-arch").addEventListener("change", (e) => save({ keep_archives: e.target.checked }));
  $("#st-pw-clear").onclick = () => sheet(`<h2>清空记住的解压密码？</h2><p class="intro">以后遇到加密压缩包需要重新输入密码。</p>`,
    async () => { await save({ archive_passwords: [] }, "已清空"); renderSettings(); }, "清空");
  $("#st-quit").onclick = () => sheet(`<h2>退出文渊？</h2><p class="intro">自动整理会停止。再次使用时双击「启动文渊」${isWin() ? "，或从开始菜单打开" : ""}。</p>`,
    async () => {
      try { await api("/api/quit", { method: "POST" }); } catch (e) { /* 服务已经关了 */ }
      document.body.innerHTML = `<div class="quit-page"><h2>文渊已退出</h2><p>再次使用时双击「启动文渊」${isWin() ? "，或从开始菜单打开" : ""}。</p></div>`;
    }, "退出");
  if (isWin()) {
    $("#st-notify").addEventListener("change", (e) => save({ notify_enabled: e.target.checked }));
    $$("#st-sendto-move button").forEach((b) => (b.onclick = () => {
      $$("#st-sendto-move button").forEach((x) => x.classList.toggle("on", x === b));
      save({ sendto_move: b.dataset.v === "1" }, b.dataset.v === "1" ? "发送后会移走原文件" : "发送后保留原文件");
    }));
    api("/api/system").then((sys) => {
      if ($("#st-autostart")) $("#st-autostart").checked = !!sys.autostart;
      if ($("#st-sendto") && sys.sendto !== null) $("#st-sendto").checked = !!sys.sendto;
    }).catch(() => {});
    $("#st-autostart").addEventListener("change", async (e) => {
      try { const r = await api("/api/system/autostart", { method: "PUT", json: { enabled: e.target.checked } }); e.target.checked = !!r.autostart; toast(r.autostart ? "已设置开机自动运行" : "已取消开机自动运行"); }
      catch (err) { e.target.checked = !e.target.checked; fail(err); }
    });
    $("#st-sendto").addEventListener("change", async (e) => {
      try { const r = await api("/api/system/sendto", { method: "PUT", json: { enabled: e.target.checked } }); toast(e.target.checked ? "已添加到右键「发送到」菜单" : "已从右键菜单移除"); }
      catch (err) { e.target.checked = !e.target.checked; fail(err); }
    });
  }
  loadSources();
  $("#st-ocr").addEventListener("change", (e) => save({ ocr_enabled: e.target.checked }, e.target.checked ? "已开启图片文字识别" : "已关闭图片文字识别"));
  $("#st-ocr-pages").addEventListener("change", (e) => save({ ocr_pdf_pages: Math.max(1, Math.min(5, Number(e.target.value) || 2)) }));
  $("#st-watch").addEventListener("change", (e) => save({ watch_enabled: e.target.checked }, e.target.checked ? "已开启自动整理" : "已暂停自动整理"));
  $("#st-jev-on").addEventListener("change", (e) => save({ jev_enabled: e.target.checked }));
  $("#st-ds-on").addEventListener("change", (e) => save({ deepseek_enabled: e.target.checked }));
  for (const [id, key] of [["#st-auto", "auto_threshold"], ["#st-review", "review_threshold"]]) {
    $(id).addEventListener("input", (e) => { $(id + "-v").textContent = e.target.value + "%"; });
    $(id).addEventListener("change", (e) => save({ [key]: Number(e.target.value) / 100 }));
  }
  const pick = async (inputId, key) => {
    try {
      const r = await api("/api/settings/pick-folder", { method: "POST" });
      if (r.path) { $(inputId).value = r.path; save({ [key]: r.path }, "文件夹已更新"); }
    } catch (e) { fail(e); }
  };
  $("#st-pick").onclick = () => pick("#st-root", "archive_root");
  $("#st-pick-inbox").onclick = () => pick("#st-inbox", "inbox_dir");
  $("#st-open").onclick = () => openPath($("#st-root").value, "open");
  $("#st-types-toggle").onclick = () => { S.typesOpen = !S.typesOpen; $("#st-types").classList.toggle("hidden", !S.typesOpen); };
  $("#st-type-add").onclick = () => typeSheet(null);
  $$("[data-type]").forEach((tr) => (tr.onclick = async () => {
    try { const all = await api("/api/types"); const t = all.find((x) => x.code === tr.dataset.type); if (t) typeSheet(t); } catch (e) { fail(e); }
  }));
  $$("[data-test]").forEach((b) => (b.onclick = async () => {
    const t = b.dataset.test;
    const res = { jev: $("#st-jev-res"), deepseek: $("#st-ds-res"), ocr: $("#st-ocr-res") }[t];
    b.disabled = true; res.innerHTML = `<span class="processing"><span class="spinner"></span>${t === "ocr" ? "正在加载识别模型…" : "正在连接…"}</span>`;
    try {
      const r = await api(`/api/settings/test/${t}`, { method: "POST" });
      res.innerHTML = t === "ocr"
        ? `<span style="color:var(--green)">${ic("check")} 识别正常</span> · ${esc(r.model || "")} · ${r.ms} 毫秒 · 识别出「${esc(r.title || "")}」`
        : `<span style="color:var(--green)">${ic("check")} 连接成功</span> · ${esc(r.model || "")} · ${r.ms} 毫秒${r.title ? ` · 示例标题「${esc(r.title)}」` : ""}`;
    } catch (e) { res.innerHTML = `<span style="color:var(--red)">${esc(e.message)}</span>`; } finally { b.disabled = false; }
  }));
}

const SRC_KIND = { wechat: "微信", wxwork: "企业微信", folder: "文件夹" };
async function loadSources(data) {
  const box = $("#st-sources");
  if (!box) return;
  try { data = data || await api("/api/sources"); } catch (e) { box.innerHTML = `<div class="row"><span class="desc">${esc(e.message)}</span></div>`; return; }
  const rows = data.sources.map((x) => `<div class="row src-row ${x.enabled ? "" : "muted"}">
      <span class="tag src-kind ${x.kind}">${SRC_KIND[x.kind] || "文件夹"}</span>
      <div class="grow" style="min-width:0"><div>${esc(x.name)}${x.exists ? "" : ` <span class="tag red">文件夹不存在</span>`}</div><div class="desc mono ellipsis" title="${esc(x.path)}">${esc(x.path)}</div></div>
      <span class="desc" title="开启以来收进来的文件数">已收 ${x.imported}</span>
      <label class="switch"><input type="checkbox" data-src-on="${x.id}" ${x.enabled ? "checked" : ""}><span></span></label>
      <button class="btn plain icon" data-src-del="${x.id}" title="移除这个来源">${ic("x")}</button></div>`).join("");
  box.innerHTML = `${rows || `<div class="row"><span class="desc grow">还没有添加来源。点「自动查找」找到本机的微信、企业微信文件夹。</span></div>`}
    <div class="row"><div class="grow"><div>认不出项目的文件</div><div class="desc">微信里也有私人文件：忽略的文件在「处理记录 → 已忽略」里，需要时可以「拿来归档」</div></div>
      <div class="segmented" id="st-src-unmatched"><button data-v="ignore" class="${data.unmatched !== "keep" ? "on" : ""}">忽略</button><button data-v="keep" class="${data.unmatched === "keep" ? "on" : ""}">放进未匹配</button></div></div>
    <div class="row"><div class="grow"></div><button class="btn" id="st-src-detect">${ic("search")}自动查找微信 / 企业微信</button><button class="btn" id="st-src-add">${ic("plus")}添加文件夹…</button></div>`;
  $$("[data-src-on]", box).forEach((c) => (c.onchange = async () => {
    try { loadSources(await api(`/api/sources/${c.dataset.srcOn}`, { method: "PUT", json: { enabled: c.checked } })); toast(c.checked ? "已开启，只收从现在起的新文件" : "已暂停这个来源"); }
    catch (e) { c.checked = !c.checked; fail(e); }
  }));
  $$("[data-src-del]", box).forEach((b) => (b.onclick = async () => {
    try { loadSources(await api(`/api/sources/${b.dataset.srcDel}`, { method: "DELETE" })); toast("已移除来源", "原文件夹里的文件不受影响"); } catch (e) { fail(e); }
  }));
  $$("#st-src-unmatched button", box).forEach((b) => (b.onclick = async () => {
    $$("#st-src-unmatched button", box).forEach((x) => x.classList.toggle("on", x === b));
    try { await api("/api/settings", { json: { source_unmatched: b.dataset.v } }); toast(b.dataset.v === "keep" ? "认不出项目的文件会放进「未匹配」" : "认不出项目的文件会被忽略"); } catch (e) { fail(e); }
  }));
  $("#st-src-detect", box).onclick = async () => {
    try {
      const r = await api("/api/sources/detect", { method: "POST" });
      loadSources(r);
      toast(r.added ? `找到并添加了 ${r.added} 个来源` : (r.found ? "找到的来源都已添加过" : "没有找到微信 / 企业微信的文件夹"),
        r.added ? "已开启，只收从现在起的新文件" : (r.found ? "" : "可以点「添加文件夹…」手动选择（微信设置 → 文件管理 里能看到位置）"));
    } catch (e) { fail(e); }
  };
  $("#st-src-add", box).onclick = async () => {
    try {
      const f = await api("/api/settings/pick-folder", { method: "POST" });
      if (!f.path) return;
      loadSources(await api("/api/sources", { json: { path: f.path } }));
      toast("已添加来源", "只收从现在起的新文件");
    } catch (e) { fail(e); }
  };
}

/* ---------------------------------------------------------------- 搜索 */
async function renderSearch(q) {
  q = q ?? S.query;
  S.query = q;
  $("#search").value = q;
  toolbar("搜索", q ? `“${q}”` : "");
  content.innerHTML = `<div class="page"><div class="group" id="sr"><div class="empty"><span class="spinner" style="display:inline-block"></span></div></div></div>`;
  let rows = [];
  try { rows = await api(`/api/search?q=${encodeURIComponent(q)}`); } catch (e) { return fail(e); }
  const hl = (t) => fzHighlight(t || "", q);
  $("#tb-sub").textContent = `“${q}” · ${rows.length} 个结果`;
  $("#sr").innerHTML = rows.length ? rows.map((r) => `<div class="result" data-path="${esc(r.rel)}">${docIcon(r.archive_name)}<div class="meta" style="flex:1;min-width:0"><div class="name" style="font-weight:500">${hl(r.archive_name)}</div>
      <div class="sub" style="color:var(--secondary);font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.customer_short || "")} · ${esc(r.project_short || "")} · ${esc(r.type_name)}${r.summary ? " · " + hl(r.summary) : ""}</div></div>
      ${r.state === "superseded" ? `<span class="tag">历史版本</span>` : ""}<button class="btn plain icon" data-ql="${esc(r.archive_path)}" title="快速查看">${ic("eye")}</button><button class="btn plain" data-loc="${esc(r.rel)}">在归档库中显示</button></div>`).join("")
    : `<div class="empty">${ic("search")}<h3>没有找到</h3>可以搜索文件名、标题、摘要、客户或项目简称，多个词用空格分隔</div>`;
  $$("[data-ql]", $("#sr")).forEach((b) => (b.onclick = () => openPath(b.dataset.ql, "quicklook")));
  $$("[data-loc]", $("#sr")).forEach((b) => (b.onclick = () => go("library", b.dataset.loc)));
}
$("#search").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.isComposing) { const q = e.target.value.trim(); if (q) go("search", q); }
  if (e.key === "Escape") { e.target.value = ""; e.target.blur(); }
});
window.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") { e.preventDefault(); $("#search").focus(); $("#search").select(); }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "o" && S.route !== "settings") { e.preventDefault(); $("#file-input").click(); }
});

/* ---------------------------------------------------------------- 启动 */
(async function init() {
  try { await refreshMeta(); } catch (e) { /* 服务未启动时由 tick 提示 */ }
  await tick(true);
  if (isWin()) $(".search kbd").textContent = "Ctrl F";
  const [route, arg] = location.hash.slice(1).split("/");
  go(ROUTES[route] ? route : "overview", arg ? decodeURIComponent(arg) : undefined);
  window.addEventListener("hashchange", () => {
    const [r, a] = location.hash.slice(1).split("/");
    if (ROUTES[r]) go(r, a ? decodeURIComponent(a) : undefined);
  });
  setInterval(() => tick(), 2500);
  setInterval(() => { if (S.route === "projects") return; refreshMeta().catch(() => {}); }, 30000);
})();
