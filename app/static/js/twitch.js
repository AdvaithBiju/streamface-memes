const $ = (id) => document.getElementById(id);

function setStatus(msg, kind = "") {
  $("status").textContent = msg;
  $("status").className = "status " + kind;
}

async function post(url, data = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

function showAccount(role, acc, emptyText) {
  $(role).textContent = acc ? `Connected as ${acc.login}` : emptyText;
  $(role).className = acc ? "ok-text" : "muted";
  $(role + "-login").textContent = acc ? "Switch account" : role === "bot" ? "Connect bot" : "Connect Twitch";
  $(role + "-logout").hidden = !acc;
}

async function refresh() {
  let s;
  try {
    s = await (await fetch("/api/twitch/status")).json();
  } catch {
    return setStatus("Can't reach the app.", "error");
  }
  $("setup-card").hidden = s.configured;
  $("redirect-uri").textContent = s.redirect_uri;
  showAccount("broadcaster", s.broadcaster, "Not connected");
  showAccount("bot", s.bot, "Not connected (replies come from the streamer account)");
  $("conn-status").textContent = s.status;
  $("conn-error").hidden = !s.last_error;
  $("conn-error").textContent = s.last_error || "";
  $("reward-title").textContent = s.reward_title;
  $("reward-state").textContent = s.reward_id
    ? "✅ Reward created by StreamFace. Redemptions are fulfilled or refunded automatically."
    : s.channel_points === false
      ? "Channel point events aren't available on this channel (Affiliate/Partner only). Chat commands still work."
      : `No reward yet. You can create one here, or make your own named “${s.reward_title}” (refunds only work for rewards created here).`;
}

$("broadcaster-logout").onclick = async () => {
  await post("/api/twitch/disconnect/broadcaster");
  setStatus("Streamer account disconnected.");
  refresh();
};
$("bot-logout").onclick = async () => {
  await post("/api/twitch/disconnect/bot");
  setStatus("Bot account disconnected.");
  refresh();
};
$("reconnect").onclick = async () => {
  await post("/api/twitch/reconnect");
  setStatus("Reconnecting…");
  setTimeout(refresh, 1500);
};
$("test-msg").onclick = async () => {
  try {
    await post("/api/twitch/test");
    setStatus("Test message sent. Check your Twitch chat.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  }
};
$("create-reward").onclick = async () => {
  try {
    await post("/api/twitch/reward", { cost: parseInt($("reward-cost").value, 10) });
    setStatus("Reward created! Viewers can redeem it now.", "ok");
    refresh();
  } catch (err) {
    setStatus(err.message, "error");
  }
};

refresh();
setInterval(refresh, 4000);
