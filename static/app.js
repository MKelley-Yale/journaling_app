const APP_VERSION = "3";  // bump with the ?v= in index.html and CACHE in sw.js

// ---------- helpers ----------
async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  if (r.status === 401) { showLock(); throw new Error("locked"); }
  if (!r.ok) {
    let msg = "Something went wrong";
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}

async function uploadPhotos(eid, files) {
  if (!files || !files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const r = await fetch(`/api/entries/${eid}/photos`, { method: "POST", body: fd });
  if (r.status === 401) { showLock(); throw new Error("locked"); }
  if (!r.ok) throw new Error("Photo upload failed");
  return r.json();
}

function renderPhotoChips(container, files, onRemove) {
  container.innerHTML = files.map((f, i) =>
    `<div class="photo-chip"><img src="${URL.createObjectURL(f)}"><button class="chip-x" data-i="${i}" type="button">×</button></div>`
  ).join("");
  container.querySelectorAll(".chip-x").forEach((b) =>
    b.onclick = () => onRemove(+b.dataset.i));
}

const $ = (sel) => document.querySelector(sel);
const view = () => $("#view");

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.add("hidden"), 2600);
}

function esc(s) {
  return (s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { weekday: "short", year: "numeric", month: "short", day: "numeric" });
}
function fmtDateTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}
function isMorning() { return new Date().getHours() < 12; }

function getLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => resolve(null),
      { timeout: 6000, maximumAge: 600000 }
    );
  });
}

// ---------- boot / auth ----------
let STATUS = null;

async function boot() {
  STATUS = await api("/api/status");
  if (!STATUS.has_pin) return showSetup();
  if (!STATUS.authed) return showLock();
  startApp();
}

function showSetup() {
  $("#app").classList.add("hidden");
  const o = $("#lock"); o.classList.remove("hidden");
  $("#lock-title").textContent = "Set a PIN";
  $("#lock-sub").textContent = "This locks the app. You'll enter it to open your journal.";
  $("#pin-btn").textContent = "Set PIN";
  $("#pin-input").value = "";
  $("#pin-btn").onclick = async () => {
    const pin = $("#pin-input").value.trim();
    try {
      await api("/api/setup-pin", "POST", { pin });
      o.classList.add("hidden"); startApp();
    } catch (e) { $("#lock-err").textContent = e.message; }
  };
}

function showLock() {
  $("#app").classList.add("hidden");
  const o = $("#lock"); o.classList.remove("hidden");
  $("#lock-title").textContent = "Welcome back";
  $("#lock-sub").textContent = "Enter your PIN.";
  $("#pin-btn").textContent = "Unlock";
  $("#pin-input").value = ""; $("#lock-err").textContent = "";
  $("#pin-input").focus();
  const submit = async () => {
    const pin = $("#pin-input").value.trim();
    try {
      await api("/api/login", "POST", { pin });
      o.classList.add("hidden"); startApp();
    } catch (e) { $("#lock-err").textContent = e.message; $("#pin-input").value = ""; }
  };
  $("#pin-btn").onclick = submit;
  $("#pin-input").onkeydown = (e) => { if (e.key === "Enter") submit(); };
}

function startApp() {
  $("#app").classList.remove("hidden");
  document.querySelectorAll(".tab").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      renderTab(b.dataset.tab);
    };
  });
  registerSW();
  renderTab("today");
}

// ---------- service worker + push ----------
async function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  try { await navigator.serviceWorker.register("/sw.js"); } catch (e) {}
}

function urlB64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    toast("Push isn't supported here. On iPhone, add the app to your Home Screen first."); return;
  }
  const perm = await Notification.requestPermission();
  if (perm !== "granted") { toast("Notifications not granted"); return; }
  const reg = await navigator.serviceWorker.ready;
  const key = STATUS.vapid_public;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlB64ToUint8Array(key),
  });
  await api("/api/push/subscribe", "POST", { subscription: sub.toJSON() });
  toast("Reminders enabled");
}

// ---------- TODAY ----------
let SESSION = null;

async function renderTab(tab) {
  if (tab === "today") return renderToday();
  if (tab === "collections") return renderCollections();
  if (tab === "calendar") return renderCalendar();
  if (tab === "lookback") return renderLookback();
  if (tab === "settings") return renderSettings();
  // Shouldn't happen — but surface it instead of silently doing nothing.
  toast("Unknown tab: " + tab + " (try Settings → Force update)");
}

function renderToday() {
  SESSION = null;
  const morning = isMorning();
  view().innerHTML = `
    <h1>Today</h1>
    <p class="muted">${morning ? "Good morning — these will lean toward yesterday." : "A few minutes for today."}</p>
    <div class="card">
      <button class="primary" id="start">Start a session</button>
      <div class="spacer"></div>
      <div class="row">
        <button class="ghost" id="freewrite">Free write</button>
        <button class="ghost" id="resurface">Resurface a past entry</button>
      </div>
    </div>`;
  $("#start").onclick = () => startSession(null, morning);
  $("#freewrite").onclick = renderFreewrite;
  $("#resurface").onclick = renderResurface;
}

async function startSession(collectionId, morning) {
  try {
    const data = await api("/api/session/start", "POST",
      { collection_id: collectionId, morning });
    SESSION = {
      collection_id: data.collection_id, morning: data.morning,
      items: data.prompts.map((p) => ({ ...p, answer: "" })),
    };
    renderSession();
  } catch (e) { toast(e.message); }
}

function excludeIds() { return SESSION.items.filter((i) => i.id != null).map((i) => i.id); }
function excludeTexts() { return SESSION.items.map((i) => i.text); }

function renderSession() {
  const cards = SESSION.items.map((it, idx) => `
    <div class="card" data-idx="${idx}">
      <span class="prompt-kind ${it.kind}">${it.kind}</span>
      <h3>${esc(it.text)}</h3>
      <textarea placeholder="Type or tap the mic on your keyboard to dictate…">${esc(it.answer)}</textarea>
      <div class="row" style="margin-top:8px">
        <button class="ghost small swap">Swap</button>
        <button class="ghost small deeper">Go deeper</button>
      </div>
      <div class="ai-followup hidden"></div>
    </div>`).join("");

  view().innerHTML = `
    <div class="row between"><h1>Session</h1><button class="link" id="cancel">Cancel</button></div>
    ${cards}
    <div class="row">
      <button class="ghost" id="more-fact">+ Factual</button>
      <button class="ghost" id="more-refl">+ Reflective</button>
    </div>
    <div class="card">
      <h3>Photos</h3>
      <input type="file" id="photos" accept="image/*" multiple />
      <div class="photo-preview row" id="photo-preview"></div>
    </div>
    <div class="spacer"></div>
    <button class="primary" id="save">Save entry</button>
    <div class="spacer"></div>`;

  view().querySelectorAll(".card").forEach((card) => {
    const idx = +card.dataset.idx;
    const ta = card.querySelector("textarea");
    if (!ta) return;
    ta.oninput = () => { SESSION.items[idx].answer = ta.value; };
    card.querySelector(".swap").onclick = () => swapPrompt(idx);
    card.querySelector(".deeper").onclick = () => goDeeper(idx, card);
  });
  $("#cancel").onclick = renderToday;
  $("#more-fact").onclick = () => morePrompts("factual");
  $("#more-refl").onclick = () => morePrompts("reflective");
  $("#save").onclick = saveSession;

  SESSION.photoFiles = SESSION.photoFiles || [];
  const refreshPhotoPreview = () =>
    renderPhotoChips($("#photo-preview"), SESSION.photoFiles, (i) => {
      SESSION.photoFiles.splice(i, 1);
      refreshPhotoPreview();
    });
  $("#photos").onchange = (e) => {
    SESSION.photoFiles = SESSION.photoFiles.concat([...e.target.files]);
    e.target.value = "";
    refreshPhotoPreview();
  };
  refreshPhotoPreview();
}

async function swapPrompt(idx) {
  const it = SESSION.items[idx];
  try {
    const data = await api("/api/prompts/swap", "POST", {
      collection_id: SESSION.collection_id, kind: it.kind, morning: SESSION.morning,
      exclude_ids: excludeIds(), exclude_texts: excludeTexts(),
    });
    if (data.prompt) { SESSION.items[idx] = { ...data.prompt, answer: "" }; renderSession(); }
    else toast("No other prompts of that kind");
  } catch (e) { toast(e.message); }
}

async function morePrompts(kind) {
  try {
    const data = await api("/api/session/more", "POST", {
      collection_id: SESSION.collection_id, kind, morning: SESSION.morning,
      exclude_ids: excludeIds(), exclude_texts: excludeTexts(),
    });
    if (!data.prompts.length) return toast("No more " + kind + " prompts");
    data.prompts.forEach((p) => SESSION.items.push({ ...p, answer: "" }));
    renderSession();
  } catch (e) { toast(e.message); }
}

async function goDeeper(idx, card) {
  const it = SESSION.items[idx];
  if (!it.answer.trim()) return toast("Write something first, then go deeper");
  const box = card.querySelector(".ai-followup");
  box.classList.remove("hidden"); box.textContent = "Thinking…";
  try {
    const data = await api("/api/ai/deeper", "POST",
      { question_text: it.text, answer_text: it.answer });
    box.textContent = data.followup;
    // append the follow-up as a new prompt to answer
    SESSION.items.splice(idx + 1, 0, { id: null, text: data.followup, kind: "reflective", answer: "" });
    setTimeout(renderSession, 700);
  } catch (e) { box.textContent = e.message; }
}

async function saveSession() {
  const answers = SESSION.items
    .filter((i) => i.answer.trim())
    .map((i) => ({ prompt_id: i.id, question_text: i.text, kind: i.kind, answer_text: i.answer }));
  const photoFiles = SESSION.photoFiles || [];
  if (!answers.length && !photoFiles.length) return toast("Nothing written yet");
  toast("Saving…");
  const loc = await getLocation();
  try {
    const res = await api("/api/entries", "POST", {
      collection_id: SESSION.collection_id, answers,
      lat: loc?.lat, lon: loc?.lon,
    });
    if (photoFiles.length) await uploadPhotos(res.id, photoFiles);
    toast(res.weather ? "Saved — " + res.weather : "Saved");
    renderToday();
  } catch (e) { toast(e.message); }
}

function renderFreewrite() {
  let photoFiles = [];
  view().innerHTML = `
    <div class="row between"><h1>Free write</h1><button class="link" id="cancel">Cancel</button></div>
    <div class="card">
      <textarea id="fw" style="min-height:240px" placeholder="Whatever's on your mind…"></textarea>
    </div>
    <div class="card">
      <h3>Photos</h3>
      <input type="file" id="fwphotos" accept="image/*" multiple />
      <div class="photo-preview row" id="fwphoto-preview"></div>
    </div>
    <button class="primary" id="save">Save</button>`;
  const refreshPhotoPreview = () =>
    renderPhotoChips($("#fwphoto-preview"), photoFiles, (i) => {
      photoFiles.splice(i, 1);
      refreshPhotoPreview();
    });
  $("#fwphotos").onchange = (e) => {
    photoFiles = photoFiles.concat([...e.target.files]);
    e.target.value = "";
    refreshPhotoPreview();
  };
  $("#cancel").onclick = renderToday;
  $("#save").onclick = async () => {
    const text = $("#fw").value.trim();
    if (!text && !photoFiles.length) return toast("Nothing written yet");
    const loc = await getLocation();
    try {
      const res = await api("/api/entries", "POST",
        { is_freewrite: true, freewrite_text: text, lat: loc?.lat, lon: loc?.lon });
      if (photoFiles.length) await uploadPhotos(res.id, photoFiles);
      toast("Saved"); renderToday();
    } catch (e) { toast(e.message); }
  };
}

async function renderResurface() {
  view().innerHTML = `<h1>From the past</h1><p class="muted">Looking…</p>`;
  try {
    const data = await api("/api/resurface");
    if (!data.answer) {
      view().innerHTML = `<h1>From the past</h1><p class="muted">Nothing to resurface yet — come back once you have older entries.</p>
        <button class="ghost" id="back">Back</button>`;
      $("#back").onclick = renderToday; return;
    }
    const a = data.answer;
    view().innerHTML = `
      <div class="row between"><h1>From the past</h1><button class="link" id="back">Back</button></div>
      ${data.on_this_day ? '<p class="muted">Around this time last year…</p>' : ""}
      <div class="card">
        <div class="entry-meta">${fmtDate(a.entry_date)}</div>
        <div class="qa"><div class="q">${esc(a.question_text)}</div><div class="a">${esc(a.answer_text)}</div></div>
        <h3>Any follow-up thoughts now?</h3>
        <textarea id="refl" placeholder="What do you think reading this back?"></textarea>
        <div class="spacer"></div>
        <button class="primary" id="save">Save reflection</button>
      </div>
      <button class="ghost" id="another">Show another</button>`;
    $("#back").onclick = renderToday;
    $("#another").onclick = renderResurface;
    $("#save").onclick = async () => {
      const text = $("#refl").value.trim();
      if (!text) return toast("Write a thought first");
      await api("/api/reflections", "POST", { answer_id: a.id, text });
      toast("Reflection saved"); renderToday();
    };
  } catch (e) { toast(e.message); }
}

// ---------- COLLECTIONS ----------
async function renderCollections() {
  view().innerHTML = `<h1>Collections</h1><p class="muted">Loading…</p>`;
  const cols = await api("/api/collections");
  const items = cols.map((c) => `
    <button class="list-item" data-id="${c.id}">
      <div class="title">${esc(c.name)}</div>
      <div class="sub">${esc(c.description || "")}</div>
      <div class="sub">${c.prompt_count} prompts · ${c.entry_count} entries${c.is_daily ? " · daily" : ""}</div>
    </button>`).join("");
  view().innerHTML = `
    <h1>Collections</h1>
    ${items}
    <div class="spacer"></div>
    <button class="ghost" id="new">+ New collection</button>`;
  view().querySelectorAll(".list-item").forEach((b) =>
    b.onclick = () => openCollection(+b.dataset.id));
  $("#new").onclick = () => newCollection(cols);
}

async function openCollection(id) {
  const data = await api("/api/collections/" + id);
  const c = data.collection;
  const prompts = data.prompts.map((p) =>
    `<div class="qa"><span class="prompt-kind ${p.kind}">${p.kind}</span><div class="q">${esc(p.text)}</div></div>`).join("");
  view().innerHTML = `
    <div class="row between"><h1>${esc(c.name)}</h1><button class="link" id="back">Back</button></div>
    <p class="muted">${esc(c.description || "")}</p>
    <button class="primary" id="start">Start a session in this collection</button>
    <h2>Prompts</h2>
    ${prompts || '<p class="muted">No prompts yet.</p>'}
    <div class="card">
      <h3>Add a prompt</h3>
      <textarea id="ptext" placeholder="Your own question…"></textarea>
      <div class="spacer"></div>
      <div class="row">
        <select id="pkind"><option value="reflective">Reflective</option><option value="factual">Factual</option></select>
        <button class="ghost" id="addp">Add</button>
      </div>
    </div>`;
  $("#back").onclick = renderCollections;
  $("#start").onclick = () => startSession(id, isMorning());
  $("#addp").onclick = async () => {
    const text = $("#ptext").value.trim();
    if (!text) return toast("Write a prompt");
    await api("/api/collections/" + id + "/prompts", "POST", { text, kind: $("#pkind").value });
    toast("Prompt added"); openCollection(id);
  };
}

function newCollection(cols) {
  const templates = cols.filter((c) => c.kind === "template");
  const tOpts = templates.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  view().innerHTML = `
    <div class="row between"><h1>New collection</h1><button class="link" id="back">Back</button></div>
    <div class="card">
      <input type="text" id="cname" placeholder="Name (e.g. a trip, a project, an event)" />
      <div class="spacer"></div>
      <input type="text" id="cdesc" placeholder="Short description (optional)" />
      <div class="spacer"></div>
      <label class="muted">Start from a template?</label>
      <select id="ctpl"><option value="">Blank</option>${tOpts}</select>
      <div class="spacer"></div>
      <button class="primary" id="create">Create</button>
    </div>`;
  $("#back").onclick = renderCollections;
  $("#create").onclick = async () => {
    const name = $("#cname").value.trim();
    if (!name) return toast("Name it first");
    const body = { name, description: $("#cdesc").value.trim() };
    const tpl = $("#ctpl").value;
    if (tpl) body.from_template_id = +tpl;
    const c = await api("/api/collections", "POST", body);
    toast("Created"); openCollection(c.id);
  };
}

// ---------- CALENDAR ----------
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

let CAL = null; // { year, month }  month is 0-based

function localDateKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function renderCalendar(year, month) {
  const now = new Date();
  if (year == null || month == null) {
    CAL = CAL || { year: now.getFullYear(), month: now.getMonth() };
  } else {
    CAL = { year, month };
  }
  const { year: y, month: m } = CAL;

  view().innerHTML = `
    <div class="row between">
      <button class="ghost small" id="prev">‹</button>
      <h1 id="calhead">${MONTH_NAMES[m]} ${y}</h1>
      <button class="ghost small" id="next">›</button>
    </div>
    <div class="cal-grid" id="calgrid"><p class="muted">Loading…</p></div>
    <div id="dayview"></div>`;

  $("#prev").onclick = () => {
    const d = new Date(y, m - 1, 1);
    renderCalendar(d.getFullYear(), d.getMonth());
  };
  $("#next").onclick = () => {
    const d = new Date(y, m + 1, 1);
    renderCalendar(d.getFullYear(), d.getMonth());
  };

  let counts = {};
  try {
    const data = await api(`/api/calendar?year=${y}&month=${m + 1}`);
    counts = data.days || {};
  } catch (e) { toast(e.message); }

  const firstDow = new Date(y, m, 1).getDay();
  const daysInMonth = new Date(y, m + 1, 0).getDate();
  const todayKey = localDateKey(new Date());

  const dowHeader = ["S", "M", "T", "W", "T", "F", "S"]
    .map((d) => `<div class="cal-dow">${d}</div>`).join("");
  const blanks = Array(firstDow).fill('<div class="cal-cell blank"></div>').join("");
  const cells = Array.from({ length: daysInMonth }, (_, i) => {
    const day = i + 1;
    const key = `${y}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const n = counts[key] || 0;
    return `<button class="cal-cell${n ? " has" : ""}${key === todayKey ? " today" : ""}"
      data-date="${key}" ${n ? "" : "disabled"}>
      <span class="cal-num">${day}</span>
      ${n ? `<span class="cal-dot">${n > 1 ? n : ""}</span>` : ""}
    </button>`;
  }).join("");

  $("#calgrid").innerHTML = dowHeader + blanks + cells;
  view().querySelectorAll(".cal-cell[data-date]").forEach((c) => {
    if (c.disabled) return;
    c.onclick = () => {
      view().querySelectorAll(".cal-cell").forEach((x) => x.classList.remove("selected"));
      c.classList.add("selected");
      showDay(c.dataset.date);
    };
  });
}

async function showDay(dateKey) {
  const box = $("#dayview");
  box.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const entries = await api("/api/entries?date=" + encodeURIComponent(dateKey));
    const [yy, mm, dd] = dateKey.split("-").map(Number);
    const heading = new Date(yy, mm - 1, dd).toLocaleDateString(undefined,
      { weekday: "long", month: "long", day: "numeric", year: "numeric" });
    if (!entries.length) {
      box.innerHTML = `<h2>${heading}</h2><p class="muted">No entries this day.</p>`;
      return;
    }
    box.innerHTML = `<h2>${heading}</h2>` + entries.map((e) => `
      <button class="list-item" data-id="${e.id}">
        <div class="title">${e.collection_name || "Free write"}</div>
        <div class="sub">${esc((e.preview || "").slice(0, 90))}${(e.preview || "").length > 90 ? "…" : ""}</div>
        <div class="sub">${e.answer_count} ${e.answer_count === 1 ? "answer" : "answers"}${e.photo_count ? ` · ${e.photo_count} 📷` : ""}${e.weather ? " · " + esc(e.weather) : ""}</div>
      </button>`).join("");
    box.querySelectorAll(".list-item").forEach((b) =>
      b.onclick = () => openEntry(+b.dataset.id, { from: "calendar" }));
  } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

// ---------- LOOK BACK ----------
async function renderLookback(q = "") {
  view().innerHTML = `
    <h1>Look Back</h1>
    <input type="text" id="search" placeholder="Search your entries…" value="${esc(q)}" />
    <div id="results"><p class="muted">Loading…</p></div>`;
  const search = $("#search");
  search.oninput = debounce(() => renderResults(search.value), 300);
  renderResults(q);
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

async function renderResults(q) {
  const entries = await api("/api/entries?q=" + encodeURIComponent(q || ""));
  const r = $("#results");
  if (!entries.length) { r.innerHTML = `<p class="muted">No entries yet.</p>`; return; }
  r.innerHTML = entries.map((e) => `
    <button class="list-item" data-id="${e.id}">
      <div class="title">${fmtDate(e.created_at)}</div>
      <div class="sub">${esc((e.preview || "").slice(0, 90))}${(e.preview || "").length > 90 ? "…" : ""}</div>
      <div class="sub">${e.collection_name || "Free write"} · ${e.answer_count} ${e.answer_count === 1 ? "answer" : "answers"}${e.photo_count ? ` · ${e.photo_count} 📷` : ""}${e.weather ? " · " + esc(e.weather) : ""}</div>
    </button>`).join("");
  r.querySelectorAll(".list-item").forEach((b) => b.onclick = () => openEntry(+b.dataset.id));
}

function fmtTimeLeft(seconds) {
  const h = Math.floor(seconds / 3600);
  if (h >= 1) return `${h} ${h === 1 ? "hour" : "hours"} left to edit`;
  const m = Math.max(1, Math.floor(seconds / 60));
  return `${m} ${m === 1 ? "minute" : "minutes"} left to edit`;
}

function goBackFrom(opts) {
  if (opts && opts.from === "calendar") return renderCalendar();
  return renderLookback();
}

async function openEntry(id, opts = {}) {
  const data = await api("/api/entries/" + id);
  const e = data.entry;
  const photos = data.photos || [];
  const editable = !!data.editable;

  const photoGrid = photos.length ? `<div class="photo-grid">${photos.map((p) => `
    <div class="photo-item">
      <img src="/api/photos/${encodeURIComponent(p.filename)}" data-full="/api/photos/${encodeURIComponent(p.filename)}">
      ${editable ? `<button class="photo-del" data-pid="${p.id}" type="button">×</button>` : ""}
    </div>`).join("")}</div>` : "";

  const qa = data.answers.map((a) => {
    const refls = a.reflections.map((rf) =>
      `<div class="reflection">${esc(rf.text)}<div class="when">${fmtDateTime(rf.created_at)}</div></div>`).join("");
    return `
      <div class="qa" data-aid="${a.id}">
        <div class="q">${esc(a.question_text)}</div>
        <div class="a">${esc(a.answer_text)}</div>
        ${refls}
        <button class="link addrefl">+ Add a reflection</button>
        <div class="refl-box hidden">
          <textarea placeholder="Looking back on this…"></textarea>
          <div class="spacer"></div><button class="ghost small saverefl">Save reflection</button>
        </div>
      </div>`;
  }).join("");

  view().innerHTML = `
    <div class="row between"><h1>${fmtDate(e.created_at)}</h1><button class="link" id="back">Back</button></div>
    <div class="entry-meta">${e.collection_name || "Free write"}${e.weather ? " · " + esc(e.weather) : ""} · ${fmtDateTime(e.created_at)}</div>
    ${editable ? `<div class="row between edit-bar">
        <span class="muted small-txt">${fmtTimeLeft(data.edit_seconds_left)}</span>
        <button class="ghost small" id="edit">Edit</button>
      </div>` : ""}
    ${photoGrid}
    ${qa}`;

  $("#back").onclick = () => goBackFrom(opts);
  if (editable) $("#edit").onclick = () => editEntry(id, data, opts);

  view().querySelectorAll(".photo-item img").forEach((img) => {
    img.onclick = () => window.open(img.dataset.full, "_blank");
  });
  view().querySelectorAll(".photo-del").forEach((b) => {
    b.onclick = async (ev) => {
      ev.stopPropagation();
      try { await api("/api/photos/" + b.dataset.pid, "DELETE"); openEntry(id, opts); }
      catch (err) { toast(err.message); }
    };
  });
  view().querySelectorAll(".qa").forEach((q) => {
    const aid = +q.dataset.aid;
    const box = q.querySelector(".refl-box");
    q.querySelector(".addrefl").onclick = () => box.classList.toggle("hidden");
    q.querySelector(".saverefl").onclick = async () => {
      const text = q.querySelector("textarea").value.trim();
      if (!text) return toast("Write a thought first");
      await api("/api/reflections", "POST", { answer_id: aid, text });
      toast("Saved"); openEntry(id, opts);
    };
  });
}

function editEntry(id, data, opts = {}) {
  const e = data.entry;
  const photos = data.photos || [];
  let newPhotos = [];

  const fields = data.answers.map((a) => `
    <div class="card" data-aid="${a.id}">
      <div class="q">${esc(a.question_text)}</div>
      <textarea class="edit-a">${esc(a.answer_text)}</textarea>
      <p class="muted small-txt">Clear the text to remove this answer.</p>
    </div>`).join("");

  const existing = photos.length ? `<div class="photo-grid">${photos.map((p) => `
    <div class="photo-item">
      <img src="/api/photos/${encodeURIComponent(p.filename)}">
      <button class="photo-del" data-pid="${p.id}" type="button">×</button>
    </div>`).join("")}</div>` : `<p class="muted">No photos yet.</p>`;

  view().innerHTML = `
    <div class="row between"><h1>Edit entry</h1><button class="link" id="cancel">Cancel</button></div>
    <div class="entry-meta">${fmtDate(e.created_at)} · ${fmtTimeLeft(data.edit_seconds_left)}</div>
    ${fields || '<p class="muted">This entry has no answers.</p>'}
    <div class="card">
      <h3>Photos</h3>
      ${existing}
      <div class="spacer"></div>
      <input type="file" id="addphotos" accept="image/*" multiple />
      <div class="photo-preview row" id="newphoto-preview"></div>
    </div>
    <div class="spacer"></div>
    <button class="primary" id="savedits">Save changes</button>
    <div class="spacer"></div>
    <button class="ghost danger" id="delentry">Delete this entry</button>
    <div class="spacer"></div>`;

  $("#cancel").onclick = () => openEntry(id, opts);

  const refreshNew = () =>
    renderPhotoChips($("#newphoto-preview"), newPhotos, (i) => {
      newPhotos.splice(i, 1);
      refreshNew();
    });
  $("#addphotos").onchange = (ev) => {
    newPhotos = newPhotos.concat([...ev.target.files]);
    ev.target.value = "";
    refreshNew();
  };

  view().querySelectorAll(".photo-del").forEach((b) => {
    b.onclick = async () => {
      try {
        await api("/api/photos/" + b.dataset.pid, "DELETE");
        const fresh = await api("/api/entries/" + id);
        editEntry(id, fresh, opts);
      } catch (err) { toast(err.message); }
    };
  });

  $("#savedits").onclick = async () => {
    const answers = [...view().querySelectorAll(".card[data-aid]")].map((c) => ({
      id: +c.dataset.aid,
      answer_text: c.querySelector(".edit-a").value,
    }));
    try {
      await api("/api/entries/" + id, "PUT", { answers });
      if (newPhotos.length) await uploadPhotos(id, newPhotos);
      toast("Changes saved");
      openEntry(id, opts);
    } catch (err) { toast(err.message); }
  };

  $("#delentry").onclick = async () => {
    if (!confirm("Delete this entry and its photos? This can't be undone.")) return;
    try {
      await api("/api/entries/" + id, "DELETE");
      toast("Entry deleted");
      goBackFrom(opts);
    } catch (err) { toast(err.message); }
  };
}

// ---------- SETTINGS ----------
async function renderSettings() {
  const s = await api("/api/settings");
  view().innerHTML = `
    <h1>Settings</h1>
    <div class="card">
      <h3>Reminders</h3>
      <p class="muted">A nudge every few days, at a random time in your window, with one follow-up if you don't engage that day.</p>
      <label>Every <input type="number" id="cmin" value="${s.cadence_min_days}" min="1" max="14" style="width:64px"> to
        <input type="number" id="cmax" value="${s.cadence_max_days}" min="1" max="14" style="width:64px"> days</label>
      <div class="spacer"></div>
      <label>Between <input type="number" id="wstart" value="${s.window_start_hour}" min="0" max="23" style="width:64px"> :00 and
        <input type="number" id="wend" value="${s.window_end_hour}" min="1" max="24" style="width:64px"> :00</label>
      <div class="spacer"></div>
      <label>Prompts per session: <input type="number" id="ssize" value="${s.session_size}" min="2" max="20" style="width:64px"></label>
      <div class="spacer"></div>
      <label>Morning (ask about yesterday) before hour: <input type="number" id="mcut" value="${s.morning_cutoff_hour}" min="0" max="23" style="width:64px"></label>
      <div class="spacer"></div>
      <button class="primary" id="savesettings">Save settings</button>
    </div>
    <div class="card">
      <h3>Notifications</h3>
      <p class="muted">On iPhone: add this app to your Home Screen first, then enable.</p>
      <div class="row">
        <button class="ghost" id="enable">Enable reminders on this device</button>
        <button class="ghost" id="test">Send test</button>
      </div>
      <p class="muted" id="nextrem"></p>
    </div>
    <div class="card">
      <h3>Account</h3>
      <button class="ghost" id="logout">Lock app</button>
    </div>
    <div class="card">
      <h3>App</h3>
      <p class="muted small-txt">Build ${APP_VERSION}. If a new feature isn't showing up,
        force an update to clear the cached app files.</p>
      <button class="ghost" id="forceupdate">Force update</button>
    </div>`;
  $("#savesettings").onclick = async () => {
    await api("/api/settings", "PUT", {
      cadence_min_days: $("#cmin").value, cadence_max_days: $("#cmax").value,
      window_start_hour: $("#wstart").value, window_end_hour: $("#wend").value,
      session_size: $("#ssize").value, morning_cutoff_hour: $("#mcut").value,
    });
    toast("Saved"); loadNext();
  };
  $("#enable").onclick = enablePush;
  $("#test").onclick = async () => { await api("/api/push/test", "POST"); toast("Test sent"); };
  $("#logout").onclick = async () => { await api("/api/logout", "POST"); showLock(); };
  $("#forceupdate").onclick = forceUpdate;
  loadNext();
}

async function forceUpdate() {
  toast("Clearing cached app files…");
  try {
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
    if (window.caches) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
  } catch (e) {}
  // Cache-busted reload so the browser can't hand back the old shell.
  location.replace("/?r=" + Date.now());
}

async function loadNext() {
  try {
    const d = await api("/api/reminders/next");
    if (d.next) $("#nextrem").textContent = "Next reminder: " + fmtDateTime(d.next.scheduled_for);
  } catch (e) {}
}

boot();
