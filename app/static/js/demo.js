const $ = (id) => document.getElementById(id);
const log = $("chat-log");
const NAMES = ["pixel_panda", "noodle_king", "gg_gary", "lurker_lucy", "speedrun_sam", "copium_carl",
  "pog_priya", "afk_alex", "clip_that_chris", "emote_emma"];

function addLine(user, text, kind = "viewer") {
  const line = document.createElement("div");
  line.className = "chat-line " + kind;
  const name = document.createElement("b");
  name.textContent = user + ": ";
  line.append(name, document.createTextNode(text));
  log.append(line);
  log.scrollTop = log.scrollHeight;
}

async function post(url, data) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) addLine("system", `Request failed (${res.status})`, "system");
}

function currentUser() {
  return $("user").value.trim() || "cool_viewer";
}

async function sendChat(text) {
  if (!text.trim()) return;
  addLine(currentUser(), text);
  await post("/api/demo/chat", { user: currentUser(), text });
}

$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sendChat($("message").value);
  $("message").value = "";
});

for (const b of document.querySelectorAll("[data-msg]")) b.onclick = () => sendChat(b.dataset.msg);

$("redeem-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("redeem-text").value;
  addLine(currentUser(), `redeemed Make a Meme: ${text}`, "redeem");
  await post("/api/demo/redeem", { user: currentUser(), text });
  $("redeem-text").value = "";
});

$("random-user").onclick = () => {
  const name = NAMES[Math.floor(Math.random() * NAMES.length)];
  $("user").value = `${name}${Math.floor(Math.random() * 90 + 10)}`;
};

$("reset-cooldowns").onclick = async () => {
  await post("/api/demo/reset-cooldowns", {});
  addLine("system", "Cooldowns reset.", "system");
};

const socket = io();
socket.on("bot_message", (m) => addLine("StreamFaceBot", m.text, "bot"));
addLine("system", "Connected to demo chat. Try !memes", "system");

// Scale the 1920x1080 overlay preview to fit its box.
const frame = document.querySelector(".overlay-frame");
const iframe = frame.querySelector("iframe");
new ResizeObserver(() => {
  iframe.style.transform = `scale(${frame.clientWidth / 1920})`;
}).observe(frame);
