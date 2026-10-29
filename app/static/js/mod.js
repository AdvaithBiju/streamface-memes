const $ = (id) => document.getElementById(id);
const SOURCE_LABELS = { chat: "chat", channel_points: "channel points", demo: "demo", editor: "editor" };
let pending = [];

function setStatus(msg, kind = "") {
  $("status").textContent = msg;
  $("status").className = "status " + kind;
}

const modInput = $("mod-name");
try { modInput.value = localStorage.getItem("modName") || ""; } catch { /* storage blocked */ }
modInput.addEventListener("input", () => {
  try { localStorage.setItem("modName", modInput.value); } catch { /* ignore */ }
});

function timeAgo(sqlTime) {
  const t = new Date(sqlTime.replace(" ", "T") + "Z");
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

async function act(id, action) {
  const res = await fetch(`/api/memes/${id}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mod: modInput.value.trim() || "mod" }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) setStatus(body.error || "Action failed.", "error");
  else setStatus(`Meme #${id} ${action === "replay" ? "replayed" : action + "d"}.`, "ok");
  load();
}

function renderPending(list) {
  pending = list;
  const box = $("pending");
  box.replaceChildren();
  $("pending-empty").hidden = list.length > 0;
  $("pending-count").textContent = list.length;
  document.title = (list.length ? `(${list.length}) ` : "") + "StreamFace Mod Queue";

  for (const m of list) {
    const card = el("article", "pending-card");
    const img = el("img");
    img.src = m.url;
    img.alt = `Meme #${m.id}`;
    const link = el("a");
    link.href = m.url;
    link.target = "_blank";
    link.append(img);

    const info = el("div", "pending-info");
    const who = el("div", "who");
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
    img.src = m.url;
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

async function load() {
  try {
    const res = await fetch("/api/queue");
    const data = await res.json();
    renderPending(data.pending);
    renderHistory(data.history);
  } catch {
    setStatus("Can't reach the server.", "error");
  }
}

document.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA"].includes(document.activeElement.tagName) || !pending.length) return;
  if (e.key === "a" || e.key === "A") act(pending[0].id, "approve");
  if (e.key === "r" || e.key === "R") act(pending[0].id, "reject");
});

const socket = io();
socket.on("connect", load);
socket.on("meme_updated", load);
setInterval(() => renderPending(pending), 30000); // refresh "x ago" labels
