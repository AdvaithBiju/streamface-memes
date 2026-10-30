// OBS overlay: plays approved memes, the vote leaderboard and the winner reveal
// one at a time, plus a small live vote widget while voting is open.
const params = new URLSearchParams(location.search);
const pos = ["left", "right", "center"].includes(params.get("pos")) ? params.get("pos") : "center";
const secondsOverride = parseFloat(params.get("seconds"));
const showVoteWidget = params.get("votes") !== "0";
document.body.classList.add("pos-" + pos);
if (params.has("preview")) document.body.classList.add("preview");

const stage = document.getElementById("stage");
const queue = [];
let current = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function enqueue(item) {
  // A meme can arrive twice (socket event + catch-up fetch); queue it once.
  if (item.kind === "meme") {
    const same = (m) => m.kind === "meme" && m.id === item.id;
    if ((current && same(current)) || queue.some(same)) return;
  }
  queue.push(item);
  if (!current) playNext();
}

// Resolves when the image has loaded; rejects on error or after `ms`, so one
// stuck image can never freeze the whole queue.
function loadImage(url, ms = 6000) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const timer = setTimeout(() => reject(new Error("image timed out")), ms);
    img.onload = () => { clearTimeout(timer); resolve(img); };
    img.onerror = () => { clearTimeout(timer); reject(new Error("image failed")); };
    img.src = url;
  });
}

// ------------------------------------------------------------------ cards

async function memeCard(m) {
  const card = el("div", "card");
  const tag = el("div", "tag");
  tag.append(el("span", "num", `#${m.id}`), " Meme by ");
  tag.append(el("b", "", m.requested_by === "streamer" ? "the streamer" : m.requested_by));
  card.append(await loadImage(m.url), tag, el("div", "timer"));
  return card;
}

async function leaderboardCard(data) {
  const card = el("div", "card board");
  card.append(el("div", "board-title", data.open ? "🏆 Meme of the Stream: so far" : "🏆 Final results"));
  const list = el("ol", "board-list");
  const images = await Promise.all(data.leaderboard.map((m) => loadImage(m.url).catch(() => el("div"))));
  for (const [i, m] of data.leaderboard.entries()) {
    const li = el("li", i === 0 ? "first" : "");
    const img = images[i];
    li.append(el("span", "rank", String(i + 1)), img,
      el("span", "who", `#${m.id} ${m.requested_by}`),
      el("span", "votes", `${m.votes} vote${m.votes === 1 ? "" : "s"}`));
    list.append(li);
  }
  if (data.open) card.append(list, el("div", "board-hint", "Type !vote <number> in chat"));
  else card.append(list);
  card.append(el("div", "timer"));
  return card;
}

async function winnerCard(w) {
  const card = el("div", "card winner");
  card.append(el("div", "crown", "👑"), el("div", "winner-title", "Meme of the Stream"));
  card.append(await loadImage(w.url));
  const tag = el("div", "tag");
  tag.append(el("span", "num", `#${w.id}`), " by ");
  tag.append(el("b", "", w.requested_by));
  tag.append(` · ${w.votes} vote${w.votes === 1 ? "" : "s"}`);
  card.append(tag, el("div", "timer"));
  return card;
}

function confetti() {
  const box = el("div", "confetti");
  const colors = ["#ffe066", "#a970ff", "#ff6b6b", "#00f593", "#4dabf7"];
  for (let i = 0; i < 60; i++) {
    const p = el("i");
    p.style.left = Math.random() * 100 + "%";
    p.style.background = colors[i % colors.length];
    p.style.animationDelay = Math.random() * 1.5 + "s";
    p.style.animationDuration = 2.5 + Math.random() * 2 + "s";
    p.style.setProperty("--drift", (Math.random() * 30 - 15) + "vw");
    box.append(p);
  }
  return box;
}

// ------------------------------------------------------------------ player

async function playNext() {
  current = queue.shift() || null;
  if (!current) return;
  const item = current;
  const seconds = secondsOverride > 0 && item.kind === "meme" ? secondsOverride : item.seconds || 8;

  let card;
  try {
    card = item.kind === "winner" ? await winnerCard(item)
      : item.kind === "leaderboard" ? await leaderboardCard(item)
      : await memeCard(item);
  } catch {
    current = null;
    return playNext(); // broken image: skip it
  }

  card.style.setProperty("--seconds", seconds + "s");
  stage.replaceChildren(card);
  // Confetti lives outside the card: a transformed parent would trap it in the card's box.
  const party = item.kind === "winner" ? confetti() : null;
  if (party) document.body.append(party);
  void card.offsetWidth; // restart animation
  card.classList.add("in");
  await sleep(seconds * 1000);
  card.classList.replace("in", "out");
  await sleep(650);
  card.remove();
  if (party) party.remove();

  if (item.kind === "meme") fetch(`/api/memes/${item.id}/shown`, { method: "POST" }).catch(() => {});
  await sleep(400);
  current = null;
  playNext();
}

// ------------------------------------------------------------------ live vote widget

const widget = document.getElementById("vote-widget");
function renderWidget(s) {
  widget.hidden = !(showVoteWidget && s.open);
  if (widget.hidden) return;
  const list = el("ol");
  for (const m of s.leaderboard.slice(0, 3)) {
    list.append(el("li", "", `#${m.id} ${m.requested_by}: ${m.votes}`));
  }
  widget.replaceChildren(el("div", "vw-title", "🏆 !vote <number>"), list);
  if (!s.leaderboard.length) widget.append(el("div", "vw-empty", "No votes yet"));
}

// ------------------------------------------------------------------ wiring

async function catchUp() {
  try {
    const res = await fetch("/api/overlay/queue");
    (await res.json()).forEach((m) => enqueue({ ...m, kind: "meme" }));
  } catch { /* server not up yet; retried below */ }
}

async function refreshVotes() {
  try {
    renderWidget(await (await fetch("/api/voting")).json());
  } catch { /* ignore */ }
}

const socket = io({ transports: ["websocket", "polling"] });
const conn = document.getElementById("conn");
socket.on("connect", () => { conn.hidden = true; catchUp(); refreshVotes(); });
socket.on("disconnect", () => { conn.hidden = false; });
socket.on("show_meme", (m) => enqueue({ ...m, kind: "meme" }));
socket.on("show_leaderboard", (d) => enqueue({ ...d, kind: "leaderboard" }));
socket.on("show_winner", (w) => enqueue({ ...w, kind: "winner" }));
socket.on("voting_updated", renderWidget);

// Don't depend on the socket alone: fetch on load and poll as a fallback.
catchUp();
refreshVotes();
setInterval(catchUp, 5000);
setInterval(refreshVotes, 10000);
