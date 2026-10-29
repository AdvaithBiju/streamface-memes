// OBS overlay: plays approved memes one at a time.
const params = new URLSearchParams(location.search);
const pos = ["left", "right", "center"].includes(params.get("pos")) ? params.get("pos") : "center";
const secondsOverride = parseFloat(params.get("seconds"));
document.body.classList.add("pos-" + pos);
if (params.has("preview")) document.body.classList.add("preview");

const stage = document.getElementById("stage");
const queue = [];
let current = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function enqueue(meme) {
  // A meme can arrive twice (socket event + catch-up fetch); queue it once.
  if ((current && current.id === meme.id) || queue.some((m) => m.id === meme.id)) return;
  queue.push(meme);
  if (!current) playNext();
}

async function playNext() {
  current = queue.shift() || null;
  if (!current) return;
  const meme = current;
  const seconds = secondsOverride > 0 ? secondsOverride : meme.seconds || 8;

  const img = new Image();
  img.src = meme.url;
  try {
    await img.decode();
  } catch {
    current = null;
    return playNext(); // broken image: skip it
  }

  const card = document.createElement("div");
  card.className = "card";
  card.style.setProperty("--seconds", seconds + "s");
  const tag = document.createElement("div");
  tag.className = "tag";
  tag.append("Meme by ");
  const name = document.createElement("b");
  name.textContent = meme.requested_by === "streamer" ? "the streamer" : meme.requested_by;
  tag.append(name);
  const timer = document.createElement("div");
  timer.className = "timer";
  card.append(img, tag, timer);
  stage.replaceChildren(card);

  void card.offsetWidth; // restart animation
  card.classList.add("in");
  await sleep(seconds * 1000);
  card.classList.replace("in", "out");
  await sleep(650);
  card.remove();

  fetch(`/api/memes/${meme.id}/shown`, { method: "POST" }).catch(() => {});
  await sleep(400);
  current = null;
  playNext();
}

async function catchUp() {
  try {
    const res = await fetch("/api/overlay/queue");
    (await res.json()).forEach(enqueue);
  } catch { /* server not up yet; socket reconnect will retry */ }
}

const socket = io({ transports: ["websocket", "polling"] });
const conn = document.getElementById("conn");
socket.on("connect", () => { conn.hidden = true; catchUp(); });
socket.on("disconnect", () => { conn.hidden = false; });
socket.on("show_meme", enqueue);

// Don't depend on the socket alone: fetch on load and poll as a fallback.
catchUp();
setInterval(catchUp, 5000);
