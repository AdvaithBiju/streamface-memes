// Mod site: sign in with Twitch (streamer + channel mods only), approve/reject memes, run voting.
const API = window.STREAMFACE_API;
const $ = (id) => document.getElementById(id);
const SOURCE_LABELS = { chat: "chat", channel_points: "channel points", demo: "demo", editor: "editor", web: "website" };
const POLL_MS = 4000;

let token = null;
let pending = [];
let pollTimer = null;

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

function timeAgo(sqlTime) {
  const t = new Date(sqlTime.replace(" ", "T") + "Z");
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

// ---------------------------------------------------------------- sign-in token

function readToken() {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has("token") || hash.has("error")) {
    history.replaceState(null, "", location.pathname + location.search);
    if (hash.get("error")) showError(hash.get("error"));
    if (hash.get("token")) {
      try { localStorage.setItem("sf_mod_token", hash.get("token")); } catch { /* storage blocked */ }
      return hash.get("token");
    }
  }
  try { return localStorage.getItem("sf_mod_token"); } catch { return null; }
}

function signOut() {
  token = null;
  try { localStorage.removeItem("sf_mod_token"); } catch { /* ignore */ }
  clearTimeout(pollTimer);
  $("dashboard").hidden = true;
  $("who").hidden = true;
  $("signin").hidden = false;
}

async function api(path, opts = {}) {
  const waking = setTimeout(() => { $("waking").hidden = false; }, 2500);
  try {
    const res = await fetch(API + path, {
      ...opts,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    });
    const body = await res.json().catch(() => ({}));
    if (res.status === 401 || res.status === 403) {
      signOut();
      if (res.status === 403) showError(body.error || "This account isn't a mod.");
      throw new Error(body.error || "Please sign in again.");
    }
    if (!res.ok) throw new Error(body.error || `Something went wrong (${res.status}).`);
    return body;
  } catch (err) {
    if (err instanceof TypeError) throw new Error("Can't reach the meme server right now.");
    throw err;
  } finally {
    clearTimeout(waking);
    $("waking").hidden = true;
  }
}

// ---------------------------------------------------------------- queue

async function act(id, action) {
  try {
    await api(`/api/memes/${id}/${action}`, { method: "POST", body: "{}" });
    setStatus(`Meme #${id} ${action === "replay" ? "replayed" : action + "d"}.`, "ok");
  } catch (err) {
    setStatus(err.message, "error");
  }
  refresh();
}

function renderPending(list) {
  pending = list;
  const box = $("pending");
  box.replaceChildren();
  $("pending-empty").hidden = list.length > 0;
  $("pending-count").textContent = list.length;
  document.title = (list.length ? `(${list.length}) ` : "") + "StreamFace Mod";

  for (const m of list) {
    const card = el("article", "pending-card");
    const link = el("a");
    link.href = API + m.url;
    link.target = "_blank";
    link.rel = "noopener";
    const img = el("img");
    img.src = API + m.url;
    img.alt = `Meme #${m.id}`;
    link.append(img);

    const info = el("div", "pending-info");
    const who = el("div", "who-line");
    who.append(el("strong", "", m.requested_by), el("span", "badge", SOURCE_LABELS[m.source] || m.source));
    info.append(
      who,
      el("div", "muted small", `#${m.id} · ${m.template_id} · ${timeAgo(m.created_at)}`),
      el("div", "caption", m.caption ? `“${m.caption}”` : "(default captions)")
    );
    const buttons = el("div", "buttons");
    const ok = el("button", "approve", "Approve");
    ok.onclick = () => act(m.id, "approve");
    const no = el("button", "ghost danger", "Reject");
    no.onclick = () => act(m.id, "reject");
    buttons.append(ok, no);
    info.append(buttons);

    card.append(link, info);
    box.append(card);
  }
}

function renderHistory(list) {
  const box = $("history");
  box.replaceChildren();
  $("history-empty").hidden = list.length > 0;
  for (const m of list) {
    const row = el("div", "history-row");
    const img = el("img");
    img.src = API + m.url;
    img.alt = "";
    img.loading = "lazy";
    const text = el("div", "history-text");
    text.append(
      el("div", "", `#${m.id} ${m.requested_by}`),
      el("div", "muted small", `${m.template_id}${m.decided_by ? " · by " + m.decided_by : ""}`)
    );
    row.append(img, text, el("span", "badge status-" + m.status, m.status));
    if (m.status === "approved" || m.status === "shown") {
      const again = el("button", "ghost", "Replay");
      again.title = "Show on the overlay again";
      again.onclick = () => act(m.id, "replay");
      row.append(again);
    }
    box.append(row);
  }
}

// Only redraw when something changed, so images don't flicker on every poll.
let lastQueue = "";
let lastVoting = "";

async function refresh() {
  clearTimeout(pollTimer);
  if (!token) return;
  try {
    const [queue, voting] = await Promise.all([api("/api/queue"), api("/api/voting")]);
    const q = JSON.stringify(queue);
    if (q !== lastQueue) {
      lastQueue = q;
      renderPending(queue.pending);
      renderHistory(queue.history);
    }
    const v = JSON.stringify(voting);
    if (v !== lastVoting) {
      lastVoting = v;
      renderVoting(voting);
    }
    showError("");
  } catch (err) {
    if (token) showError(err.message);
  }
  if (token) pollTimer = setTimeout(refresh, POLL_MS);
}

document.addEventListener("keydown", (e) => {
  if (!token || ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName) || !pending.length) return;
  if (e.key === "a" || e.key === "A") act(pending[0].id, "approve");
  if (e.key === "r" || e.key === "R") act(pending[0].id, "reject");
});

// ---------------------------------------------------------------- Meme of the Stream

function renderVoting(v) {
  $("vote-state").textContent = v.open ? "open" : "closed";
  $("vote-state").className = "badge " + (v.open ? "status-approved" : "");
  $("vote-open").disabled = v.open;
  $("vote-close").disabled = !v.open;
  $("vote-show").disabled = !v.leaderboard.length;
  const board = $("vote-board");
  board.replaceChildren();
  for (const m of v.leaderboard) {
    const li = el("li", m.id === v.winner_id ? "winner" : "");
    const img = el("img");
    img.src = API + m.url;
    img.alt = "";
    li.append(img, el("span", "", `#${m.id} ${m.requested_by}`), el("b", "", `${m.votes}`));
    board.append(li);
  }
  $("vote-total").textContent = v.round_id
    ? `${v.total_votes} vote${v.total_votes === 1 ? "" : "s"} this round` + (v.open ? "" : " (closed)")
    : "No voting rounds yet.";
}

async function votingAction(action, okMsg) {
  try {
    const v = await api(`/api/voting/${action}`, { method: "POST", body: "{}" });
    setStatus(okMsg, "ok");
    lastVoting = JSON.stringify(v);
    renderVoting(v);
  } catch (err) {
    setStatus(err.message, "error");
  }
}

$("vote-open").onclick = () => votingAction("open", "Voting is open. Chat can !vote now.");
$("vote-show").onclick = () => votingAction("show", "Leaderboard sent to the overlay.");
$("vote-close").onclick = () => {
  if (confirm("Close voting and show the winner on stream?")) votingAction("close", "Winner crowned!");
};

// ---------------------------------------------------------------- start

$("sign-in").onclick = () => { location.href = `${API}/auth/login?site=mod`; };
$("sign-out").onclick = signOut;
setInterval(() => { if (token) renderPending(pending); }, 30000); // refresh "x ago" labels

async function start() {
  token = readToken();
  if (!token) return signOut();
  let me;
  try {
    me = await api("/api/me");
  } catch (err) {
    if (token) showError(err.message);
    return;
  }
  if (me.role !== "mod") {
    signOut();
    return showError("This account isn't a mod of the channel.");
  }
  $("who-name").textContent = me.login;
  $("who").hidden = false;
  $("signin").hidden = true;
  $("dashboard").hidden = false;
  refresh();
}

start();
