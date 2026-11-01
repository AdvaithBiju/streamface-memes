// Viewers' site: sign in with Twitch, pick a meme, place faces (the streamer's, or
// screenshots the viewer adds) and text, then send it to the mods.
//
// The editor is the streamer editor's (app/static/js/editor.js): layers use
// template-pixel coordinates, (x, y) is the top-left of the unrotated box and
// rotation is clockwise degrees around its centre, same as app/meme.py, so the
// server render matches this preview.
const API = window.STREAMFACE_API;
const $ = (id) => document.getElementById(id);
const FONT = 'Impact, Haettenschweiler, "Arial Narrow Bold", "Arial Black", sans-serif';
const LINE_HEIGHT = 1.1;
const MIN_FONT = 10;
const STATUS_TEXT = {
  pending: "Waiting for a mod",
  approved: "Approved! On stream soon",
  shown: "Shown on stream",
  rejected: "Not approved",
};
const TOUCH = matchMedia("(pointer: coarse)").matches;

const canvas = $("stage");
const ctx = canvas.getContext("2d");
const state = { template: null, bg: null, layers: [], sel: -1, faces: [], drag: null };
const faceImgs = new Map();
let token = null;
let me = null;
let popular = null;
let cooldownUntil = 0;
let mineTimer = null;
let voteTimer = null;
let lastVoting = "";
let stream = null;
let editing = null;   // the text layer being typed into on the meme
let lastTap = { time: 0, x: 0, y: 0 };

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function setStatus(msg, kind = "", id = "status") {
  $(id).textContent = msg;
  $(id).className = "status " + kind;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = !msg;
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Couldn't load that picture."));
    img.src = src;
  });
}

// ---------------------------------------------------------------- sign-in token

function readToken() {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has("token") || hash.has("error")) {
    history.replaceState(null, "", location.pathname + location.search);
    if (hash.get("error")) showError(hash.get("error"));
    if (hash.get("token")) {
      try { localStorage.setItem("sf_token", hash.get("token")); } catch { /* storage blocked */ }
      return hash.get("token");
    }
  }
  try { return localStorage.getItem("sf_token"); } catch { return null; }
}

function signOut() {
  token = null;
  try { localStorage.removeItem("sf_token"); } catch { /* ignore */ }
  clearTimeout(mineTimer);
  clearTimeout(voteTimer);
  stopCamera();
  $("maker").hidden = true;
  $("who").hidden = true;
  $("signin").hidden = false;
}

// ---------------------------------------------------------------- API

async function api(path, opts = {}) {
  const waking = setTimeout(() => { $("waking").hidden = false; }, 2500);
  const headers = { Authorization: `Bearer ${token}` };
  if (typeof opts.body === "string") headers["Content-Type"] = "application/json";
  try {
    const res = await fetch(API + path, { ...opts, headers });
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) {
      signOut();
      throw new Error("Please sign in again.");
    }
    if (!res.ok) throw new Error(body.error || `Something went wrong (${res.status}).`);
    return body;
  } catch (err) {
    if (err instanceof TypeError) throw new Error("Can't reach the meme server right now. Try again in a minute.");
    throw err;
  } finally {
    clearTimeout(waking);
    $("waking").hidden = true;
  }
}

const postJSON = (path, data) => api(path, { method: "POST", body: JSON.stringify(data) });

// ---------------------------------------------------------------- geometry

const selected = () => state.layers[state.sel] || null;
const center = (l) => ({ x: l.x + l.width / 2, y: l.y + l.height / 2 });
const rad = (deg) => (deg * Math.PI) / 180;

// Screen pixels -> template pixels (the canvas is CSS-scaled).
function toCanvas(e) {
  const r = canvas.getBoundingClientRect();
  return {
    x: ((e.clientX - r.left) * canvas.width) / r.width,
    y: ((e.clientY - r.top) * canvas.height) / r.height,
  };
}

// Template point -> layer-local point (origin at centre, unrotated).
function toLocal(l, p) {
  const c = center(l);
  const dx = p.x - c.x, dy = p.y - c.y;
  const a = rad(l.rotation);
  return {
    x: dx * Math.cos(a) + dy * Math.sin(a),
    y: -dx * Math.sin(a) + dy * Math.cos(a),
  };
}

// How many template pixels one screen pixel is, for handle sizes.
function px() {
  const r = canvas.getBoundingClientRect();
  return r.width ? canvas.width / r.width : 1;
}

// ---------------------------------------------------------------- text

const textOf = (l) => (l.uppercase ? l.text.toUpperCase() : l.text);

// Greedy word wrap; mirrors wrap_text() in app/meme.py.
function wrap(text, maxWidth) {
  const lines = [];
  for (const paragraph of text.split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      const test = line ? line + " " + word : word;
      if (line && ctx.measureText(test).width > maxWidth) {
        lines.push(line);
        line = word;
      } else {
        line = test;
      }
    }
    lines.push(line);
  }
  return lines;
}

// Shrink until the text fits the box height; mirrors fit_text().
function fitText(l) {
  let size = l.size;
  let lines;
  for (;;) {
    ctx.font = `${size}px ${FONT}`;
    lines = wrap(textOf(l), l.width);
    if (lines.length * size * LINE_HEIGHT <= l.height || size <= MIN_FONT) break;
    size -= 2;
  }
  return { size, lines };
}

function drawText(l) {
  if (!textOf(l).trim()) {
    // Empty caption box: show its hint faintly so people know where to double-click.
    // Only the preview shows it; the server never renders it.
    if (!l.hint && state.layers[state.sel] !== l) return;
    ctx.save();
    ctx.globalAlpha = 0.45;
    drawText({ ...l, text: l.hint || "Double-click to type", color: "#ffffff", stroke: "#000000" });
    ctx.restore();
    return;
  }
  const { size, lines } = fitText(l);
  const lh = size * LINE_HEIGHT;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.lineJoin = "round";
  ctx.fillStyle = l.color;
  ctx.strokeStyle = l.stroke;
  ctx.lineWidth = l.outline * 2; // canvas strokes straddle the edge; Pillow's go outward
  const top = -(lines.length * lh) / 2;
  lines.forEach((line, i) => {
    const y = top + lh * (i + 0.5);
    if (l.outline > 0) ctx.strokeText(line, 0, y);
    ctx.fillText(line, 0, y);
  });
}

// ---------------------------------------------------------------- drawing

function withTransform(l, fn) {
  const c = center(l);
  ctx.save();
  ctx.translate(c.x, c.y);
  ctx.rotate(rad(l.rotation));
  fn();
  ctx.restore();
}

function drawLayer(l) {
  if (l === editing) return; // the text box over the canvas shows it while typing
  withTransform(l, () => {
    if (l.type === "face") {
      const img = faceImgs.get(l.face_id);
      if (!img) return;
      if (l.flip) ctx.scale(-1, 1);
      ctx.drawImage(img, -l.width / 2, -l.height / 2, l.width, l.height);
    } else {
      drawText(l);
    }
  });
}

function handles(l) {
  const k = px();
  return {
    resize: { x: l.width / 2, y: l.height / 2 },
    rotate: { x: 0, y: -l.height / 2 - (TOUCH ? 36 : 28) * k },
    r: (TOUCH ? 14 : 9) * k,
  };
}

function drawSelection(l) {
  const k = px();
  const h = handles(l);
  withTransform(l, () => {
    ctx.lineWidth = 2 * k;
    ctx.strokeStyle = "#a970ff";
    ctx.setLineDash([6 * k, 4 * k]);
    ctx.strokeRect(-l.width / 2, -l.height / 2, l.width, l.height);
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(0, -l.height / 2);
    ctx.lineTo(h.rotate.x, h.rotate.y);
    ctx.stroke();
    for (const p of [h.resize, h.rotate]) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, h.r, 0, Math.PI * 2);
      ctx.fillStyle = "#fff";
      ctx.fill();
      ctx.stroke();
    }
  });
}

function draw() {
  if (!state.bg) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.bg, 0, 0, canvas.width, canvas.height);
  state.layers.forEach(drawLayer);
  const s = selected();
  if (s) drawSelection(s);
  if (editing) placeInline();
}

// ---------------------------------------------------------------- layers

// The viewer's newest screenshot fills the template's face spots; the streamer's face otherwise.
function defaultFaceId() {
  const face = state.faces.filter((f) => f.mine).pop() || state.faces[0];
  return face ? face.id : null;
}

function faceLayer(faceId, box) {
  return { type: "face", face_id: faceId, rotation: 0, flip: false, color_match: true, ...box };
}

function textLayer(box, text) {
  return {
    type: "text", text, rotation: 0, uppercase: true,
    color: "#ffffff", stroke: "#000000",
    outline: Math.max(2, Math.round((box.size || 48) / 12)),
    size: 48, ...box,
  };
}

// Template captions start filled in with the meme's own text (e.g. TOP TEXT / BOTTOM TEXT).
function layersFromTemplate(t) {
  const layers = [];
  const faceId = defaultFaceId();
  if (faceId !== null) {
    for (const s of t.face_slots || []) layers.push(faceLayer(faceId, { ...s }));
  }
  // Memes without face spots (e.g. popular ones) get the viewer's newest screenshot in the middle.
  const mine = state.faces.filter((f) => f.mine).pop();
  if (!(t.face_slots || []).length && mine) {
    const img = faceImgs.get(mine.id);
    const w = Math.round(Math.min(t.width, t.height) * 0.3);
    const h = Math.round(img ? (w * img.naturalHeight) / img.naturalWidth : w * 1.25);
    layers.push(faceLayer(mine.id, { x: Math.round((t.width - w) / 2), y: Math.round((t.height - h) / 2), width: w, height: h }));
  }
  for (const c of t.captions || []) {
    const { default: text = "", ...box } = c;
    layers.push({ ...textLayer(box, text), hint: text });
  }
  return layers;
}

function addFace(faceId) {
  if (!state.template) return setStatus("Pick a meme first.", "warn");
  const img = faceImgs.get(faceId);
  const w = Math.round(Math.min(canvas.width, canvas.height) * 0.3);
  const h = Math.round(img ? (w * img.naturalHeight) / img.naturalWidth : w * 1.25);
  state.layers.push(faceLayer(faceId, {
    x: Math.round((canvas.width - w) / 2), y: Math.round((canvas.height - h) / 2), width: w, height: h,
  }));
  select(state.layers.length - 1);
}

function addText() {
  if (!state.template) return setStatus("Pick a meme first.", "warn");
  const w = Math.round(canvas.width * 0.8);
  const h = Math.round(canvas.height * 0.2);
  const size = Math.max(24, Math.round(canvas.width / 12));
  state.layers.push(textLayer(
    { x: Math.round((canvas.width - w) / 2), y: Math.round((canvas.height - h) / 2), width: w, height: h, size }, ""
  ));
  startEditing(state.layers.length - 1);
}

function select(i) {
  if (editing && state.layers[i] !== editing) stopEditing();
  state.sel = i;
  syncPanel();
  draw();
}

// ---------------------------------------------------------------- typing on the meme

const inline = $("inline-text");

function placeInline() {
  const l = editing;
  const k = canvas.getBoundingClientRect().width / canvas.width;
  const size = Math.max(fitText({ ...l, text: l.text || l.hint || "M" }).size * k, 14);
  Object.assign(inline.style, {
    left: `${canvas.offsetLeft + l.x * k}px`,
    top: `${canvas.offsetTop + l.y * k}px`,
    width: `${l.width * k}px`,
    height: `${l.height * k}px`,
    transform: `rotate(${l.rotation}deg)`,
    fontSize: `${size}px`,
    color: l.color,
    textTransform: l.uppercase ? "uppercase" : "none",
    webkitTextStroke: `${Math.max(1, l.outline * k * 0.6)}px ${l.stroke}`,
  });
}

function startEditing(i) {
  const l = state.layers[i];
  if (!l || l.type !== "text") return;
  select(i);
  editing = l;
  inline.value = l.text;
  inline.placeholder = l.hint || "Type here";
  inline.maxLength = me.caption_max;
  inline.hidden = false;
  placeInline();
  draw();
  // After the click that started this has finished, so it doesn't steal the focus back.
  setTimeout(() => { inline.focus(); inline.select(); });
}

function stopEditing() {
  if (!editing) return;
  editing = null;
  inline.hidden = true;
  syncPanel();
  draw();
}

inline.addEventListener("input", () => {
  editing.text = inline.value;
  syncPanel();
});
inline.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" && !e.shiftKey) || e.key === "Escape") {
    e.preventDefault();
    stopEditing();
  }
});
inline.addEventListener("blur", stopEditing);

// ---------------------------------------------------------------- property panel

function syncPanel() {
  const l = selected();
  $("no-selection").hidden = !!l;
  $("face-panel").hidden = !l || l.type !== "face";
  $("text-panel").hidden = !l || l.type !== "text";
  $("layer-actions").hidden = !l;
  if (!l) return;
  const panel = $(l.type === "face" ? "face-panel" : "text-panel");
  for (const input of panel.querySelectorAll("[data-prop]")) {
    const v = l[input.dataset.prop];
    if (input.type === "checkbox") input.checked = !!v;
    else input.value = typeof v === "number" ? Math.round(v) : v;
  }
  if (l.type === "face") $("face-select").value = String(l.face_id);
  else $("text-input").placeholder = l.hint || "Your caption";
}

for (const input of document.querySelectorAll("[data-prop]")) {
  input.addEventListener("input", () => {
    const l = selected();
    if (!l) return;
    let v = input.type === "checkbox" ? input.checked
      : input.type === "range" ? parseFloat(input.value)
      : input.value;
    if (typeof v === "number" && Number.isNaN(v)) return;
    l[input.dataset.prop] = v;
    if (input.dataset.prop === "size") l.outline = Math.max(2, Math.round(v / 12));
    draw();
  });
}

$("face-select").addEventListener("change", (e) => {
  const l = selected();
  if (l && l.type === "face") { l.face_id = parseInt(e.target.value, 10); draw(); }
});

$("layer-up").onclick = () => moveLayer(1);
$("layer-down").onclick = () => moveLayer(-1);
function moveLayer(dir) {
  const i = state.sel, j = i + dir;
  if (i < 0 || j < 0 || j >= state.layers.length) return;
  [state.layers[i], state.layers[j]] = [state.layers[j], state.layers[i]];
  select(j);
}

$("layer-dup").onclick = () => {
  const l = selected();
  if (!l) return;
  const shift = Math.round(canvas.width / 30);
  state.layers.splice(state.sel + 1, 0, { ...l, x: l.x + shift, y: l.y + shift });
  select(state.sel + 1);
};

$("layer-del").onclick = deleteSelected;
function deleteSelected() {
  if (state.sel < 0) return;
  state.layers.splice(state.sel, 1);
  select(-1);
}

$("add-text").onclick = addText;

$("reset").onclick = () => {
  if (!state.template) return;
  state.layers = layersFromTemplate(state.template);
  select(-1);
  setStatus("");
};

// ---------------------------------------------------------------- pointer interaction

function hitHandle(l, p) {
  const h = handles(l);
  const local = toLocal(l, p);
  const near = (q) => Math.hypot(local.x - q.x, local.y - q.y) <= h.r * 1.6;
  if (near(h.rotate)) return "rotate";
  if (near(h.resize)) return "resize";
  return null;
}

function hitLayer(p) {
  for (let i = state.layers.length - 1; i >= 0; i--) {
    const l = state.layers[i];
    const local = toLocal(l, p);
    if (Math.abs(local.x) <= l.width / 2 && Math.abs(local.y) <= l.height / 2) return i;
  }
  return -1;
}

// Double-click (or double-tap): edit the text under the pointer, or add text there.
function doubleTap(e) {
  const now = Date.now();
  const double = now - lastTap.time < 400 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 25;
  lastTap = double ? { time: 0, x: 0, y: 0 } : { time: now, x: e.clientX, y: e.clientY };
  return double;
}

function addTextAt(p) {
  const w = Math.round(canvas.width * 0.6);
  const h = Math.round(canvas.height * 0.18);
  const size = Math.max(24, Math.round(canvas.width / 12));
  state.layers.push(textLayer({ x: Math.round(p.x - w / 2), y: Math.round(p.y - h / 2), width: w, height: h, size }, ""));
  startEditing(state.layers.length - 1);
}

canvas.addEventListener("pointerdown", (e) => {
  if (!state.bg) return;
  const p = toCanvas(e);
  if (doubleTap(e)) {
    const i = hitLayer(p);
    if (i >= 0 && state.layers[i].type === "text") startEditing(i);
    else if (i < 0) addTextAt(p);
    e.preventDefault();
    return;
  }
  const s = selected();
  const handle = s && hitHandle(s, p);
  if (handle) {
    state.drag = { mode: handle, start: { width: s.width, height: s.height } };
  } else {
    const i = hitLayer(p);
    select(i);
    if (i < 0) return;
    const l = state.layers[i];
    state.drag = { mode: "move", dx: p.x - l.x, dy: p.y - l.y };
  }
  canvas.setPointerCapture(e.pointerId);
  e.preventDefault();
});

canvas.addEventListener("pointermove", (e) => {
  const p = toCanvas(e);
  const l = selected();
  if (!state.drag || !l) {
    if (state.bg) {
      const handle = l && hitHandle(l, p);
      canvas.style.cursor = handle === "rotate" ? "grab" : handle === "resize" ? "nwse-resize"
        : hitLayer(p) >= 0 ? "move" : "default";
    }
    return;
  }
  const d = state.drag;
  if (d.mode === "move") {
    l.x = p.x - d.dx;
    l.y = p.y - d.dy;
  } else if (d.mode === "resize") {
    // Resize around the centre so rotated layers stay put. Faces keep their shape.
    const c = center(l);
    const local = toLocal(l, p);
    let w = Math.max(10, Math.abs(local.x) * 2);
    let h = Math.max(10, Math.abs(local.y) * 2);
    if (l.type === "face" ? !e.altKey : e.shiftKey) {
      const scale = Math.max(w / d.start.width, h / d.start.height);
      w = d.start.width * scale;
      h = d.start.height * scale;
    }
    l.width = w;
    l.height = h;
    l.x = c.x - w / 2;
    l.y = c.y - h / 2;
  } else if (d.mode === "rotate") {
    const c = center(l);
    let deg = (Math.atan2(p.y - c.y, p.x - c.x) * 180) / Math.PI + 90;
    if (deg > 180) deg -= 360;
    const snap = e.shiftKey ? 15 : TOUCH ? 5 : 1;
    l.rotation = Math.round(deg / snap) * snap;
  }
  draw();
  syncPanel();
});

const endDrag = () => { state.drag = null; };
canvas.addEventListener("pointerup", endDrag);
canvas.addEventListener("pointercancel", endDrag);

document.addEventListener("keydown", (e) => {
  const l = selected();
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
  if (!l || typing) return;
  const step = e.shiftKey ? 10 : 1;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[e.key]) {
    l.x += moves[e.key][0];
    l.y += moves[e.key][1];
    draw();
    e.preventDefault();
  } else if (e.key === "Delete" || e.key === "Backspace") {
    deleteSelected();
    e.preventDefault();
  } else if (e.key === "Escape") {
    select(-1);
  }
});

new ResizeObserver(draw).observe($("stage-box"));

// ---------------------------------------------------------------- templates

function thumb(name, src, onclick) {
  const b = el("button", "template");
  b.type = "button";
  b.title = name;
  const img = el("img");
  img.alt = "";
  img.loading = "lazy";
  img.referrerPolicy = "no-referrer";
  img.src = src;
  b.append(img, el("span", "", name));
  b.onclick = () => onclick(b);
  return b;
}

async function loadTemplates() {
  const list = await api("/api/viewer/templates");
  const box = $("templates");
  box.replaceChildren();
  $("templates-empty").hidden = list.length > 0;
  for (const t of list) {
    const b = thumb(t.name, API + t.url, () => openTemplate(t));
    b.dataset.id = t.id;
    box.append(b);
  }
  if (state.template) markSelected(state.template.id);
}

function markSelected(id) {
  document.querySelectorAll(".template").forEach((b) => b.classList.toggle("selected", b.dataset.id === id));
}

async function openTemplate(t) {
  setStatus("Loading meme…");
  let bg;
  try {
    bg = await loadImage(API + t.url);
  } catch (err) {
    return setStatus(err.message, "error");
  }
  state.template = t;
  state.bg = bg;
  canvas.width = bg.naturalWidth;
  canvas.height = bg.naturalHeight;
  state.layers = layersFromTemplate(t);
  markSelected(t.id);
  $("editor").hidden = false;
  select(-1);
  setStatus(state.layers.some((l) => l.type === "face") ? "Double-click the text on the meme to write your captions."
    : "Add a face: upload a screenshot at the top, or tap one of the faces there.");
  $("editor").scrollIntoView({ behavior: "smooth", block: "start" });
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t === tab);
    for (const p of document.querySelectorAll(".tab-panel")) p.hidden = p.id !== "tab-" + tab.dataset.tab;
    if (tab.dataset.tab === "popular") loadPopular();
  };
}

async function loadPopular() {
  if (popular) return;
  $("popular").replaceChildren(el("p", "muted small", "Loading…"));
  try {
    popular = await api("/api/viewer/popular");
  } catch (err) {
    $("popular").replaceChildren(el("p", "status error", err.message));
    return;
  }
  renderPopular();
}

function renderPopular() {
  const q = $("popular-search").value.trim().toLowerCase();
  const box = $("popular");
  box.replaceChildren();
  for (const m of (popular || []).filter((m) => m.name.toLowerCase().includes(q))) {
    box.append(thumb(m.name, m.url, (b) => importPopular(m, b)));
  }
}
$("popular-search").addEventListener("input", renderPopular);

async function importPopular(m, button) {
  button.disabled = true;
  setStatus(`Loading “${m.name}”…`);
  try {
    const t = await postJSON("/api/viewer/popular/import", { id: m.id });
    await openTemplate(t);
    loadTemplates().catch(() => {});
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- faces

async function loadFaces() {
  state.faces = await api("/api/viewer/faces");
  await Promise.all(state.faces.map(async (f) => {
    if (faceImgs.has(f.id)) return;
    try { faceImgs.set(f.id, await loadImage(API + f.url)); } catch { /* skip broken face */ }
  }));
  const box = $("faces");
  box.replaceChildren();
  const options = $("face-select");
  options.replaceChildren();
  let n = 0;
  for (const f of state.faces) {
    const label = f.mine ? `Your face ${++n}` : "Streamer";
    const item = el("div", "face-item");
    const b = el("button", "face-btn");
    b.type = "button";
    b.title = `Add: ${label}`;
    const img = el("img");
    img.alt = label;
    img.src = API + f.url;
    b.append(img, el("span", "", f.mine ? "Yours" : "Streamer"));
    b.onclick = () => addFace(f.id);
    item.append(b);
    if (f.mine) {
      const del = el("button", "face-del", "×");
      del.type = "button";
      del.title = "Delete this face";
      del.setAttribute("aria-label", `Delete ${label}`);
      del.onclick = () => deleteFace(f.id);
      item.append(del);
    }
    box.append(item);
    options.add(new Option(label, String(f.id)));
  }
  if (!state.faces.length) box.append(el("p", "muted small", "No faces yet."));
}

async function uploadFace(blob, source) {
  if (!blob || !blob.type.startsWith("image/")) return setStatus("That isn't a picture.", "error", "face-status");
  setStatus("Finding the face…", "", "face-status");
  const fd = new FormData();
  fd.append("photo", blob, blob.name || "screenshot.png");
  fd.append("source", source);
  try {
    const face = await api("/api/viewer/faces", { method: "POST", body: fd });
    await loadFaces();
    if (state.template) {
      addFace(face.id);
      setStatus("Face cut out and added to your meme. Drag it into place.", "ok", "face-status");
    } else {
      setStatus("Face cut out! Now pick a meme below. It goes into the meme's face spots.", "ok", "face-status");
    }
  } catch (err) {
    setStatus(err.message, "error", "face-status");
  }
}

async function deleteFace(id) {
  if (!confirm("Delete this face?")) return;
  try {
    await api(`/api/viewer/faces/${id}`, { method: "DELETE" });
  } catch (err) {
    return setStatus(err.message, "error", "face-status");
  }
  state.layers = state.layers.filter((l) => l.type !== "face" || l.face_id !== id);
  faceImgs.delete(id);
  select(-1);
  await loadFaces();
}

$("face-file").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (file) uploadFace(file, "upload");
});

// Paste a screenshot straight from the clipboard.
document.addEventListener("paste", (e) => {
  if (!token || $("maker").hidden) return;
  const file = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
  if (!file) return;
  e.preventDefault();
  uploadFace(file, "paste");
});

// Or drop one anywhere on the page.
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  if (!token || $("maker").hidden) return;
  const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith("image/"));
  if (!file) return;
  e.preventDefault();
  uploadFace(file, "upload");
});

$("cam-start").onclick = async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720, facingMode: "user" } });
  } catch (err) {
    return setStatus("Couldn't open the camera: " + err.message, "error", "face-status");
  }
  $("video").srcObject = stream;
  $("cam").hidden = false;
  $("cam-start").disabled = true;
};

function stopCamera() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
  $("cam").hidden = true;
  $("cam-start").disabled = false;
}
$("cam-stop").onclick = stopCamera;

$("cam-snap").onclick = () => {
  const video = $("video");
  const snap = document.createElement("canvas");
  snap.width = video.videoWidth;
  snap.height = video.videoHeight;
  snap.getContext("2d").drawImage(video, 0, 0);
  stopCamera();
  snap.toBlob((blob) => uploadFace(blob, "webcam"), "image/png");
};

// ---------------------------------------------------------------- submit + cooldown

function tickCooldown() {
  const left = Math.ceil((cooldownUntil - Date.now()) / 1000);
  const btn = $("submit");
  if (left > 0) {
    btn.disabled = true;
    btn.textContent = `Next meme in ${left}s`;
    setTimeout(tickCooldown, 1000);
  } else {
    btn.disabled = false;
    btn.textContent = "Send to the mods";
  }
}

$("submit").onclick = async () => {
  if (!state.template) return setStatus("Pick a meme first.", "warn");
  if (!state.layers.some((l) => l.type === "face")) return setStatus("Add a face to your meme first.", "warn");
  const layers = state.layers.map(({ hint, ...l }) => l);
  $("submit").disabled = true;
  setStatus("Sending…");
  try {
    const meme = await postJSON("/api/viewer/memes", { template_id: state.template.id, layers });
    setStatus(`Sent! Meme #${meme.id} is waiting for a mod.`, "ok");
    select(-1);
    cooldownUntil = Date.now() + me.cooldown_seconds * 1000;
    tickCooldown();
    loadMine();
  } catch (err) {
    setStatus(err.message, "error");
    $("submit").disabled = false;
  }
};

// ---------------------------------------------------------------- your memes

async function loadMine() {
  clearTimeout(mineTimer);
  if (!token) return;
  let list = [];
  try {
    list = await api("/api/viewer/memes");
  } catch {
    mineTimer = setTimeout(loadMine, 15000);
    return;
  }
  const box = $("mine");
  box.replaceChildren();
  $("mine-empty").hidden = list.length > 0;
  for (const m of list) {
    const card = el("figure", "meme");
    const img = el("img");
    img.src = API + m.url;
    img.alt = `Meme #${m.id}`;
    img.loading = "lazy";
    const cap = el("figcaption");
    cap.append(el("span", "muted", `#${m.id}`), el("span", `badge status-${m.status}`, STATUS_TEXT[m.status] || m.status));
    card.append(img, cap);
    box.append(card);
  }
  // Check often while something is waiting on a mod.
  mineTimer = setTimeout(loadMine, list.some((m) => m.status === "pending" || m.status === "approved") ? 5000 : 30000);
}

// ---------------------------------------------------------------- Meme of the Stream voting

function myVote(roundId) {
  try { return Number(localStorage.getItem(`sf_vote_${roundId}`)) || null; } catch { return null; }
}

async function loadVoting() {
  clearTimeout(voteTimer);
  if (!token) return;
  try {
    renderVoting(await api("/api/voting"));
  } catch { /* try again on the next poll */ }
  voteTimer = setTimeout(loadVoting, 10000);
}

function renderVoting(v) {
  const key = JSON.stringify([v.open, v.round_id, v.candidates]);
  if (key === lastVoting) return;   // don't redraw the images on every poll
  lastVoting = key;
  $("vote-card").hidden = !v.open || !v.candidates.length;
  if ($("vote-card").hidden) return;
  const mine = myVote(v.round_id);
  const box = $("vote-list");
  box.replaceChildren();
  for (const m of v.candidates) {
    const card = el("figure", "meme" + (m.id === mine ? " voted" : ""));
    const img = el("img");
    img.src = API + m.url;
    img.alt = `Meme #${m.id} by ${m.requested_by}`;
    img.loading = "lazy";
    const cap = el("figcaption");
    const who = el("span");
    who.append(el("b", "", `#${m.id}`), ` ${m.requested_by}`);
    const button = el("button", m.id === mine ? "small" : "ghost small", m.id === mine ? "Voted ✓" : "Vote");
    button.type = "button";
    button.onclick = () => castVote(v.round_id, m.id, button);
    cap.append(who, el("span", "muted", `${m.votes} vote${m.votes === 1 ? "" : "s"}`), button);
    card.append(img, cap);
    box.append(card);
  }
}

async function castVote(roundId, memeId, button) {
  button.disabled = true;
  try {
    const v = await postJSON("/api/viewer/vote", { meme_id: memeId });
    try { localStorage.setItem(`sf_vote_${roundId}`, String(memeId)); } catch { /* storage blocked */ }
    setStatus(`You voted for #${memeId}!`, "ok", "vote-status");
    lastVoting = "";
    renderVoting(v);
  } catch (err) {
    setStatus(err.message, "error", "vote-status");
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- start

$("sign-in").onclick = () => { location.href = `${API}/auth/login?site=user`; };
$("sign-out").onclick = signOut;

async function start() {
  token = readToken();
  if (!token) return signOut();
  try {
    me = await api("/api/me");
  } catch (err) {
    if (token) showError(err.message);
    return;
  }
  $("who-name").textContent = me.login;
  $("who").hidden = false;
  $("signin").hidden = true;
  $("maker").hidden = false;
  $("text-input").maxLength = me.caption_max;
  try {
    await Promise.all([loadFaces(), loadTemplates()]);
  } catch (err) {
    showError(err.message);
  }
  loadMine();
  loadVoting();
  loadPopular();
}

start();
