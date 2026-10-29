// Meme editor. Layers use template-pixel coordinates: (x, y) is the top-left of
// the unrotated box, rotation is clockwise degrees around its centre. Same model
// as app/meme.py, so the server render matches this preview.

const $ = (id) => document.getElementById(id);
const canvas = $("stage");
const ctx = canvas.getContext("2d");
const FONT = 'Impact, Haettenschweiler, "Arial Narrow Bold", "Arial Black", sans-serif';
const LINE_HEIGHT = 1.1;
const MIN_FONT = 10;

const state = {
  templates: [],
  template: null,
  bg: null,
  layers: [],
  sel: -1,
  faces: [],
  drag: null,
};
const faceImgs = new Map();
let popular = null;

// ---------------------------------------------------------------- helpers

function setStatus(msg, kind = "") {
  $("status").textContent = msg;
  $("status").className = "status " + kind;
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Couldn't load " + src));
    img.src = src;
  });
}

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

function postJSON(url, data) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

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
  if (!textOf(l).trim()) return;
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
    rotate: { x: 0, y: -l.height / 2 - 28 * k },
    r: 9 * k,
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
}

// ---------------------------------------------------------------- layers

function defaultFaceId() {
  return state.faces.length ? state.faces[0].id : null;
}

function faceLayer(faceId, box) {
  return { type: "face", face_id: faceId, rotation: 0, flip: false, color_match: true, ...box };
}

function textLayer(box, text, style = {}) {
  return {
    type: "text", text, rotation: 0, uppercase: true,
    color: "#ffffff", stroke: "#000000",
    outline: Math.max(2, Math.round((box.size || 48) / 12)),
    size: 48, ...box, ...style,
  };
}

function layersFromTemplate(t) {
  const layers = [];
  const faceId = defaultFaceId();
  if (faceId !== null) {
    for (const s of t.face_slots || []) layers.push(faceLayer(faceId, { ...s }));
  }
  for (const c of t.captions || []) {
    const { default: text = "", ...box } = c;
    layers.push(textLayer(box, text));
  }
  return layers;
}

function addFace(faceId) {
  if (!state.template) return setStatus("Pick a meme template first.", "warn");
  const img = faceImgs.get(faceId);
  const w = Math.round(Math.min(canvas.width, canvas.height) * 0.3);
  const h = Math.round(img ? (w * img.naturalHeight) / img.naturalWidth : w * 1.25);
  state.layers.push(faceLayer(faceId, {
    x: Math.round((canvas.width - w) / 2), y: Math.round((canvas.height - h) / 2), width: w, height: h,
  }));
  select(state.layers.length - 1);
}

function addText() {
  if (!state.template) return setStatus("Pick a meme template first.", "warn");
  const w = Math.round(canvas.width * 0.8);
  const h = Math.round(canvas.height * 0.2);
  const size = Math.max(24, Math.round(canvas.width / 12));
  state.layers.push(textLayer(
    { x: Math.round((canvas.width - w) / 2), y: Math.round((canvas.height - h) / 2), width: w, height: h, size },
    "YOUR TEXT"
  ));
  select(state.layers.length - 1);
}

function select(i) {
  state.sel = i;
  syncPanel();
  draw();
}

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
}

for (const input of document.querySelectorAll("[data-prop]")) {
  input.addEventListener("input", () => {
    const l = selected();
    if (!l) return;
    const prop = input.dataset.prop;
    let v = input.type === "checkbox" ? input.checked
      : input.type === "number" || input.type === "range" ? parseFloat(input.value)
      : input.value;
    if (typeof v === "number" && Number.isNaN(v)) return;

    const c = center(l);
    if ((prop === "width" || prop === "height") && l.type === "face" && $("lock-aspect").checked) {
      const ratio = l.width / l.height;
      if (prop === "width") { l.width = v; l.height = v / ratio; } else { l.height = v; l.width = v * ratio; }
      syncPanel();
    } else {
      l[prop] = v;
    }
    // Typing a new size keeps the layer centred where it was.
    if (prop === "width" || prop === "height") {
      l.x = c.x - l.width / 2;
      l.y = c.y - l.height / 2;
    }
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
  state.layers.splice(state.sel + 1, 0, { ...l, x: l.x + 20, y: l.y + 20 });
  select(state.sel + 1);
};

$("layer-del").onclick = deleteSelected;
function deleteSelected() {
  if (state.sel < 0) return;
  state.layers.splice(state.sel, 1);
  select(-1);
}

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

canvas.addEventListener("pointerdown", (e) => {
  if (!state.bg) return;
  const p = toCanvas(e);
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
    // Resize symmetrically around the centre so rotated layers stay put.
    const c = center(l);
    const local = toLocal(l, p);
    let w = Math.max(10, Math.abs(local.x) * 2);
    let h = Math.max(10, Math.abs(local.y) * 2);
    const lock = l.type === "face" ? $("lock-aspect").checked && !e.altKey : e.shiftKey;
    if (lock) {
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
    if (e.shiftKey) deg = Math.round(deg / 15) * 15;
    l.rotation = Math.round(deg);
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

// ---------------------------------------------------------------- templates

async function loadTemplates() {
  state.templates = await api("/api/templates");
  const grid = $("template-grid");
  grid.innerHTML = "";
  for (const t of state.templates) {
    const item = document.createElement("div");
    item.className = "thumb" + (state.template && state.template.id === t.id ? " active" : "");
    item.title = t.name;
    item.dataset.id = t.id;
    item.innerHTML = `<img alt=""><span></span>`;
    item.querySelector("img").src = t.url;
    item.querySelector("span").textContent = t.name;
    item.onclick = () => openTemplate(t);
    if (t.source !== "builtin") {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "thumb-del";
      del.title = "Delete template";
      del.textContent = "×";
      del.onclick = async (ev) => {
        ev.stopPropagation();
        if (!confirm(`Delete template "${t.name}"?`)) return;
        await api(`/api/templates/${encodeURIComponent(t.id)}`, { method: "DELETE" });
        await loadTemplates();
      };
      item.appendChild(del);
    }
    grid.appendChild(item);
  }
}

async function openTemplate(t) {
  setStatus("Loading template…");
  try {
    state.bg = await loadImage(t.url);
  } catch (err) {
    return setStatus(err.message, "error");
  }
  state.template = t;
  canvas.width = state.bg.naturalWidth;
  canvas.height = state.bg.naturalHeight;
  state.layers = layersFromTemplate(t);
  $("stage-empty").hidden = true;
  canvas.hidden = false;
  $("out-width").value = canvas.width;
  updateOutSize();
  select(-1);
  setStatus(t.face_slots && t.face_slots.length && !state.faces.length
    ? "This template has face slots. Add your face on the setup page first." : "", "warn");
  for (const el of $("template-grid").children) el.classList.toggle("active", el.dataset.id === t.id);
}

$("reset-layout").onclick = () => {
  if (!state.template) return;
  state.layers = layersFromTemplate(state.template);
  select(-1);
};

// Tabs
for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t === tab);
    for (const p of document.querySelectorAll(".tab-panel")) p.hidden = p.id !== "tab-" + tab.dataset.tab;
    if (tab.dataset.tab === "popular") loadPopular();
  };
}

async function loadPopular() {
  if (popular) return;
  $("popular-grid").innerHTML = '<p class="muted small">Loading…</p>';
  try {
    popular = await api("/api/imgflip");
  } catch (err) {
    $("popular-grid").innerHTML = "";
    return setStatus(err.message, "error");
  }
  renderPopular();
}

function renderPopular() {
  const q = $("popular-search").value.trim().toLowerCase();
  const grid = $("popular-grid");
  grid.innerHTML = "";
  for (const m of (popular || []).filter((m) => m.name.toLowerCase().includes(q))) {
    const item = document.createElement("div");
    item.className = "thumb";
    item.title = m.name;
    item.innerHTML = `<img alt="" loading="lazy" referrerpolicy="no-referrer"><span></span>`;
    item.querySelector("img").src = m.url;
    item.querySelector("span").textContent = m.name;
    item.onclick = () => importPopular(m);
    grid.appendChild(item);
  }
}
$("popular-search").addEventListener("input", renderPopular);

async function importPopular(m) {
  setStatus(`Importing "${m.name}"…`);
  try {
    const t = await postJSON("/api/imgflip/import", { id: m.id });
    await loadTemplates();
    await openTemplate(t);
    setStatus(`Imported "${m.name}". Add your face and drag it into place.`, "ok");
  } catch (err) {
    setStatus(err.message, "error");
  }
}

$("template-upload").addEventListener("submit", async (e) => {
  e.preventDefault();
  setStatus("Uploading…");
  try {
    const t = await api("/api/templates", { method: "POST", body: new FormData(e.target) });
    e.target.reset();
    await loadTemplates();
    await openTemplate(t);
    setStatus("Meme uploaded. Add your face and drag it into place.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  }
});

// ---------------------------------------------------------------- faces

async function loadFaces() {
  state.faces = await api("/api/faces");
  await Promise.all(state.faces.map(async (f) => {
    try { faceImgs.set(f.id, await loadImage(f.url)); } catch { /* skip broken face */ }
  }));
  const strip = $("face-strip");
  strip.innerHTML = "";
  $("no-faces").hidden = state.faces.length > 0;
  const faceSelect = $("face-select");
  faceSelect.innerHTML = "";
  for (const f of state.faces) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "face-btn";
    b.title = `Add face #${f.id}`;
    b.innerHTML = `<img alt=""><span>+ Face</span>`;
    b.querySelector("img").src = f.url;
    b.onclick = () => addFace(f.id);
    strip.appendChild(b);
    faceSelect.add(new Option(`Face #${f.id}`, String(f.id)));
  }
}

$("add-text").onclick = addText;

// ---------------------------------------------------------------- export

function updateOutSize() {
  const w = parseInt($("out-width").value, 10);
  $("out-size").textContent = state.template && w
    ? `Output: ${w} × ${Math.round((canvas.height * w) / canvas.width)} px` : "";
}
$("out-width").addEventListener("input", updateOutSize);

function exportLayers() {
  return state.layers.map((l) => ({ ...l }));
}

$("generate").onclick = async () => {
  if (!state.template) return setStatus("Pick a meme template first.", "warn");
  setStatus("Rendering…");
  try {
    const res = await postJSON("/api/render", {
      template_id: state.template.id,
      layers: exportLayers(),
      out_width: parseInt($("out-width").value, 10) || null,
    });
    $("result").hidden = false;
    $("result-img").src = res.url;
    $("result-download").href = res.url;
    $("result-download").download = `streamface-meme-${res.id}.png`;
    $("send-stream").dataset.id = res.id;
    $("send-stream").disabled = false;
    setStatus("Meme saved!", "ok");
    loadRecent();
  } catch (err) {
    setStatus(err.message, "error");
  }
};

$("send-stream").onclick = async () => {
  const id = $("send-stream").dataset.id;
  if (!id) return;
  try {
    await postJSON(`/api/memes/${id}/send`, {});
    $("send-stream").disabled = true;
    setStatus("Sent to the stream overlay!", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  }
};

$("save-template").onclick = async () => {
  if (!state.template) return setStatus("Pick a meme template first.", "warn");
  const name = prompt("Template name (chat will use it later, e.g. !meme <name>):", state.template.name);
  if (name === null) return;
  try {
    const t = await postJSON("/api/templates/from-layout", {
      base_id: state.template.id, name, layers: exportLayers(),
    });
    await loadTemplates();
    setStatus(`Saved template "${t.name}" (id: ${t.id}).`, "ok");
  } catch (err) {
    setStatus(err.message, "error");
  }
};

async function loadRecent() {
  const memes = await api("/api/memes");
  const grid = $("recent");
  grid.innerHTML = memes.length ? "" : '<p class="muted small">Nothing yet.</p>';
  for (const m of memes) {
    const a = document.createElement("a");
    a.className = "thumb";
    a.href = m.url;
    a.target = "_blank";
    a.title = m.caption || m.template_id;
    a.innerHTML = `<img alt="" loading="lazy">`;
    a.querySelector("img").src = m.url;
    grid.appendChild(a);
  }
}

// Redraw handles at the right size when the layout changes.
new ResizeObserver(draw).observe($("stage-box"));

canvas.hidden = true;
(async () => {
  try {
    await Promise.all([loadFaces(), loadTemplates()]);
    loadRecent();
  } catch (err) {
    setStatus(err.message, "error");
  }
})();
