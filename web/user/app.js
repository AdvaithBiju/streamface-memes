// Viewers' site: sign in with Twitch, pick a template, write captions, send for approval.
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

const canvas = $("preview");
const ctx = canvas.getContext("2d");
let token = null;
let me = null;
let template = null;
let bg = null;
let cooldownUntil = 0;
let mineTimer = null;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function setStatus(msg, kind = "") {
  $("status").textContent = msg;
  $("status").className = "status " + kind;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = !msg;
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
  $("maker").hidden = true;
  $("who").hidden = true;
  $("signin").hidden = false;
}

// ---------------------------------------------------------------- API

async function api(path, opts = {}) {
  const waking = setTimeout(() => { $("waking").hidden = false; }, 2500);
  try {
    const res = await fetch(API + path, {
      ...opts,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(opts.headers || {}) },
    });
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

// ---------------------------------------------------------------- preview drawing

function wrap(text, maxWidth) {
  const lines = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const test = line ? line + " " + word : word;
    if (line && ctx.measureText(test).width > maxWidth) {
      lines.push(line);
      line = word;
    } else {
      line = test;
    }
  }
  lines.push(line);
  return lines;
}

function withBox(box, fn) {
  ctx.save();
  ctx.translate(box.x + box.width / 2, box.y + box.height / 2);
  ctx.rotate(((box.rotation || 0) * Math.PI) / 180);
  fn();
  ctx.restore();
}

function drawFaceSlot(s) {
  withBox(s, () => {
    ctx.beginPath();
    ctx.ellipse(0, 0, s.width / 2, s.height / 2, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(169, 112, 255, 0.55)";
    ctx.fill();
    ctx.lineWidth = Math.max(2, s.width / 40);
    ctx.setLineDash([s.width / 12, s.width / 16]);
    ctx.strokeStyle = "#fff";
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = `${Math.round(s.width * 0.4)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("🙂", 0, 0);
  });
}

function drawCaption(c, text) {
  text = text.toUpperCase();
  if (!text.trim()) return;
  let size = c.size || 48;
  let lines;
  for (;;) {
    ctx.font = `${size}px ${FONT}`;
    lines = wrap(text, c.width);
    if (lines.length * size * LINE_HEIGHT <= c.height || size <= MIN_FONT) break;
    size -= 2;
  }
  const outline = c.outline ?? Math.max(2, Math.round((c.size || 48) / 12));
  withBox(c, () => {
    const lh = size * LINE_HEIGHT;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineJoin = "round";
    ctx.fillStyle = c.color || "#ffffff";
    ctx.strokeStyle = c.stroke || "#000000";
    ctx.lineWidth = outline * 2;
    const top = -(lines.length * lh) / 2;
    lines.forEach((line, i) => {
      const y = top + lh * (i + 0.5);
      if (outline > 0) ctx.strokeText(line, 0, y);
      ctx.fillText(line, 0, y);
    });
  });
}

function draw() {
  if (!template || !bg) return;
  canvas.width = template.width;
  canvas.height = template.height;
  ctx.drawImage(bg, 0, 0, template.width, template.height);
  template.face_slots.forEach(drawFaceSlot);
  const inputs = [...document.querySelectorAll("#captions input")];
  template.captions.forEach((c, i) => drawCaption(c, inputs[i] ? inputs[i].value : ""));
}

// ---------------------------------------------------------------- templates

async function loadTemplates() {
  const list = await api("/api/viewer/templates");
  const box = $("templates");
  box.replaceChildren();
  $("templates-empty").hidden = list.length > 0;
  for (const t of list) {
    const b = el("button", "template");
    b.type = "button";
    const img = el("img");
    img.src = API + t.url;
    img.alt = "";
    img.loading = "lazy";
    b.append(img, el("span", "", t.name));
    b.onclick = () => pick(t, b);
    box.append(b);
  }
}

function pick(t, button) {
  document.querySelectorAll(".template.selected").forEach((b) => b.classList.remove("selected"));
  button.classList.add("selected");
  template = t;
  bg = null;
  const img = new Image();
  img.onload = () => { if (template === t) { bg = img; draw(); } };
  img.src = API + t.url;

  const box = $("captions");
  box.replaceChildren();
  t.captions.forEach((c, i) => {
    const label = el("label", "caption-field");
    label.append(el("span", "muted small", t.captions.length > 1 ? `Caption ${i + 1}` : "Caption"));
    const input = el("input");
    input.type = "text";
    input.maxLength = me.caption_max;
    input.placeholder = c.default || "";
    input.addEventListener("input", draw);
    label.append(input);
    box.append(label);
  });
  setStatus("");
  $("editor").hidden = false;
  $("editor").scrollIntoView({ behavior: "smooth", block: "start" });
  box.querySelector("input")?.focus({ preventScroll: true });
}

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
  if (!template) return;
  const captions = [...document.querySelectorAll("#captions input")].map((i) => i.value.trim());
  if (!captions.some(Boolean)) return setStatus("Write at least one caption.", "warn");
  $("submit").disabled = true;
  setStatus("Sending…");
  try {
    const meme = await api("/api/viewer/memes", {
      method: "POST",
      body: JSON.stringify({ template_id: template.id, captions }),
    });
    setStatus(`Sent! Meme #${meme.id} is waiting for a mod.`, "ok");
    document.querySelectorAll("#captions input").forEach((i) => { i.value = ""; });
    draw();
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
  try {
    await loadTemplates();
  } catch (err) {
    showError(err.message);
  }
  loadMine();
}

start();
