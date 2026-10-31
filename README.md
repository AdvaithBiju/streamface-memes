# StreamFace Memes

**Twitch viewers turn chat commands into live, mod-approved memes starring the streamer's own face.**

A viewer types `!meme drake homework vs gaming` in chat or redeems channel points. StreamFace pastes a cartoony cutout of the streamer's face onto the meme. A mod approves it, and it pops up on stream through an OBS overlay. At the end of the stream, chat votes for the **Meme of the Stream** with `!vote`.

Built for the **Codex x TwitchCon Hackathon**.

### Ground rules
- **Only the streamer's face**, uploaded by the streamer. Viewers can't upload faces.
- **Cut-and-paste cartoon style**: a soft-edged oval cutout pasted onto the meme, *not* a realistic deepfake.
- **Every viewer meme goes through a mod** before it appears on stream.
- **Viewers only add a short caption**, which has to pass a length, link, @mention and profanity filter.

---

## Features

| Page | What it does |
|---|---|
| **`/setup`** | Upload 1–3 face photos or take a webcam snapshot. MediaPipe finds the face and the app saves a transparent oval cutout. |
| **`/editor`** | A drag-and-drop meme maker for the streamer: 8 built-in classics, the top 100 Imgflip templates, or your own image. Move, resize and rotate faces and captions. Export a PNG or send it to the mod queue for approval. |
| **`/mod`** | Live approval queue (<kbd>A</kbd>/<kbd>R</kbd> shortcuts), history with replay, and the Meme of the Stream controls. |
| **`/overlay`** | Transparent OBS browser source. Memes pop in with their number and requester and queue up if several arrive at once. Also shows a live vote widget, the leaderboard and a winner reveal with confetti. |
| **`/twitch`** | Sign in with Twitch, add an optional bot account, create the "Make a Meme" channel point reward, and see the connection status. |
| **`/demo`** | Fake Twitch chat and channel point redemptions, with an overlay preview. Test everything without going live. |

**Online sites** (deployed on Vercel, see [DEPLOY.md](DEPLOY.md)):

| Site | What it does |
|---|---|
| **Viewers' site** (`web/user`) | Viewers sign in with Twitch, pick a template, write captions with a live preview, and send the meme for approval. They can see whether each of their memes was approved. |
| **Mods' site** (`web/mod`) | The streamer and their Twitch mods sign in to approve or reject memes and run Meme of the Stream from any device. Other accounts are refused. |

---

## Setup

### 1. Install (Windows)

You need Python 3.11+ (tested on 3.14).

```powershell
git clone https://github.com/AdvaithBiju/streamface-memes.git
cd streamface-memes
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

(On macOS or Linux: `source .venv/bin/activate` and `cp .env.example .env`.)

### 2. Run it

```powershell
python run.py
```

Open **http://localhost:5000**. Leave this window open while you stream. To stop the app, close it or press Ctrl+C.

On first start the app downloads two things:
- MediaPipe's small face model (about 230 KB) into `models/`. If MediaPipe isn't available, the app uses OpenCV's built-in face detector instead.
- The 8 built-in meme images from Imgflip into `templates/originals/`.

### 3. Add your face

Open **/setup**. Upload a clear, front-facing photo or take a webcam snapshot, and check that the cutout preview looks right.

### 4. Add the overlay to OBS

1. In OBS: **Sources → + → Browser**.
2. **URL:** `http://localhost:5000/overlay` · **Width:** `1920` · **Height:** `1080` (or your canvas size).
3. Keep the default custom CSS, which keeps the background transparent. Put the source at the **top** of your sources list.

Overlay URL options:

| Option | Effect |
|---|---|
| `?pos=left` / `?pos=right` | Where memes appear (default: centre) |
| `?seconds=10` | How long each meme stays |
| `?votes=0` | Hide the live vote widget |
| `?preview=1` | Checkerboard background, for viewing in a normal browser tab |

If the overlay was added before the app was running, right-click the source → **Properties** → **Refresh cache of current page**.

### 5. Connect Twitch

1. Go to **https://dev.twitch.tv/console/apps** → **Register Your Application**:
   - **OAuth Redirect URL:** `http://localhost:5000/twitch/callback` (must match exactly)
   - **Category:** Chat Bot · **Client Type:** Confidential
2. Click **Manage**, copy the **Client ID**, click **New Secret**, and put both values in `.env`:
   ```
   TWITCH_CLIENT_ID=your_client_id
   TWITCH_CLIENT_SECRET=your_client_secret
   ```
3. Restart the app and open **http://localhost:5000/twitch**.
4. Click **Connect Twitch** and sign in as **the channel you stream on**. The status should change to *connected to #yourchannel*.
5. Optional:
   - **Connect bot:** sign in as a second account (e.g. `yournamebot`) so the replies come from that account instead of yours.
   - **Create reward:** Affiliates and Partners can add the "Make a Meme" channel point reward.
6. Click **Send test message to chat**.

There are no tokens to copy by hand. The app uses Twitch's normal sign-in page, saves the tokens in `data/twitch.json` (git-ignored), and refreshes them automatically.

---

## Using it on stream

### Chat commands

| Command | What it does |
|---|---|
| `!memes` | Lists the available templates |
| `!meme <name> <caption>` | Makes a meme, e.g. `!meme drake homework vs gaming` |
| `!vote <number>` | Votes for Meme of the Stream while voting is open |

- **Multiple captions:** split them with `vs` or `|`, e.g. `!meme distracted new game | me | my backlog`.
- **Template names:** chat can type any part of a template's id or name, so `!meme roll` finds Roll Safe.
- **Channel points:** the **"Make a Meme"** reward takes the same text without `!meme`, e.g. `twobuttons stay on stream | touch grass`.
  - **Refunds:** points are refunded automatically if the meme is refused or a mod rejects it.
  - **Fulfilled:** the redemption is marked fulfilled when the meme is approved.

### Moderating

Open **/mod** on a second screen, or give your mods the link if they're on the same PC.
- **Approve** sends a meme to the overlay. **Reject** drops it, and the bot tells the viewer.
- <kbd>A</kbd> and <kbd>R</kbd> approve or reject the oldest waiting meme.
- **Replay** shows an approved meme again.

### Meme of the Stream

1. Near the end of stream, click **Open voting** on /mod.
   - Chat votes with `!vote <number>`. The number is shown on every meme on stream.
   - Viewer memes approved in the last `VOTE_WINDOW_HOURS` hours are in the running.
   - Each viewer gets one vote and can change it.
2. While voting is open, a small top-3 widget shows live on the overlay. **Show leaderboard on stream** shows the full top 5.
3. **Close & crown winner** shows the winning meme with a crown and confetti, and the bot announces it in chat.

### Guard rails

Every viewer meme passes through these checks:
- **Per-viewer cooldown.**
- **Queue limit** on memes waiting for approval.
- **Caption limits:** a length cap, and captions with links, @mentions or profanity are refused.
- **Bot replies:** the bot tells the viewer why a meme was refused, and when it's queued, approved or rejected.

---

## Configuration (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Where the app listens (local only by default) |
| `COOLDOWN_SECONDS` | `60` | Per-viewer cooldown between memes |
| `QUEUE_LIMIT` | `10` | Max memes waiting for approval |
| `CAPTION_MAX_LENGTH` | `80` | Max caption length |
| `OVERLAY_SECONDS` | `8` | How long each meme stays on screen |
| `VOTE_WINDOW_HOURS` | `12` | How far back memes count for `!vote` |
| `DEMO_MODE` | `true` | Enables `/demo` (set `false` when live) |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | | From your Twitch app |
| `TWITCH_REDIRECT_URI` | `http://localhost:5000/twitch/callback` | Must match the Twitch app |
| `TWITCH_REWARD_TITLE` / `TWITCH_REWARD_COST` | `Make a Meme` / `500` | Channel point reward |
| `DATABASE_URL` | | Online only: Postgres (Neon). Uses SQLite when blank |
| `PUBLIC_URL` | `http://localhost:5000` | This server's address (Twitch sign-in comes back here) |
| `ADMIN_PASSWORD` | | Online only: password for the streamer pages |
| `USER_SITE_URL` / `MOD_SITE_URL` | | Online only: the two Vercel sites |
| `MOD_LOGINS` | | Extra Twitch logins allowed on the mods' site |

---

## Demo mode (no Twitch needed)

Open **/demo** and **/mod** side by side:
1. Send `!meme drake homework vs gaming` from the fake chat. 🎲 switches to a random viewer.
2. Approve it on /mod and watch it in the overlay preview (or in OBS).
3. Open voting on /mod, send `!vote <number>` from a few viewers, then close voting to see the winner reveal.

The demo has quick buttons for the filter cases (links, unknown meme) and a channel point redemption simulator.

---

## Privacy & safety

- **Runs on the streamer's own PC by default.** Nothing about the streamer's face is uploaded anywhere, and the app only listens on `127.0.0.1`. If you deploy it online (DEPLOY.md), the face photos are stored in your own Neon database.
- **Online, everything is locked by default:** the streamer pages need `ADMIN_PASSWORD`, the mods' site only lets in the streamer and their Twitch mods, and viewers have to sign in with Twitch. Sign-in asks Twitch for no permissions; it only learns the username.
- **Git-ignored:** face photos, generated memes, the database and Twitch tokens all live in `data/`, `generated/` and `templates/user/`.
- **Copyright:** the meme template images are copyrighted, so they aren't in this repo. `templates/templates.json` only holds the image links and the face and caption positions, and the images are downloaded on first start.
- **Mods first:** no viewer meme reaches the stream without a mod's approval.

---

## How it works

```
Twitch chat / channel points ──EventSub WebSocket──► twitch.py
/demo fake chat ─────────────────────────────────────► commands.py  (!meme, !memes, !vote)
                                                           │
                                                           ▼
                pipeline.py: caption filter → cooldown → queue limit → render (meme.py) → "pending"
                                                           │
                         /mod ── approve / reject ─────────┤  (Socket.IO pushes every change)
                                                           ▼
                         /overlay (OBS) ◄── show_meme / leaderboard / winner
                         Twitch chat    ◄── bot replies (Helix Send Chat Message)
```

- **Face cutout** (`face.py`): MediaPipe face detection, crop expanded to include hair and chin, a feathered oval mask, then a transparent PNG.
- **Rendering** (`meme.py`):
  - Faces are resized and rotated into each slot and nudged slightly toward the slot's colours.
  - Captions use the classic white Impact style with a black outline, wrapped and auto-shrunk to fit their box.
  - The browser editor uses the same layout rules, so the preview matches the final PNG.
- **Live updates:** Flask-SocketIO pushes changes to /mod, /demo and /overlay, and the overlay also polls as a fallback.

### Project layout

```
app/
  __init__.py        Flask app factory
  config.py          settings + .env loading
  db.py              SQLite locally, Postgres online (same SQL)
  storage.py         online: keeps data files in Postgres across restarts
  auth.py            who can use what online (admin password, viewer and mod sign-in)
  face.py            face detection + oval cutout
  meme.py            meme renderer (faces + captions -> PNG)
  memetemplates.py   template registry (built-in + your own)
  imgflip.py         popular templates from Imgflip
  pipeline.py        request -> filter/cooldown -> render -> approve -> overlay
  commands.py        !meme / !memes / !vote / channel point handling
  voting.py          Meme of the Stream rounds, votes, winner
  filters.py         caption filter (length, links, @mentions, profanity)
  twitch.py          Twitch sign-in, EventSub WebSocket, chat replies, redemptions
  net.py             shared HTTPS settings
  extensions.py      Socket.IO
  routes/            setup, editor, stream (mod/overlay/demo/voting), twitch, sites (viewer + mod sites)
  pages/             HTML pages
  static/            CSS / JS (plain, no framework)
templates/templates.json   built-in template layouts (images downloaded on first start)
web/user/                  viewers' site (static, deployed on Vercel)
web/mod/                   mods' site (static, deployed on Vercel)
Dockerfile, render.yaml    backend deploy on Render
tests/                     pytest suite (offline, uses temp folders)
run.py
```

### Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

The tests run fully offline against temporary folders, with a fake Twitch. They never touch your `data/` folder. Set `TEST_DATABASE_URL` to a throwaway Postgres to run the same tests on Postgres.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| OBS shows nothing | Make sure `python run.py` is running, then refresh the browser source's cache. Test with `/overlay?preview=1` in a browser. |
| `/twitch` says the connection was "redirected" | Your network (school or office Wi-Fi) is blocking Twitch's live connection. Use another network, like home Wi-Fi or a phone hotspot. |
| `CERTIFICATE_VERIFY_FAILED … Basic Constraints` | Antivirus HTTPS scanning (e.g. Sophos) clashes with Python 3.13+'s strict checks. The app already handles this in `app/net.py`. |
| "No face found" | Use a well-lit, front-facing photo where the face is reasonably large. |
| Twitch sign-in error about the redirect URI | The OAuth Redirect URL in your Twitch app must be exactly `http://localhost:5000/twitch/callback`. |
| Channel point refunds don't happen | Refunds only work for the reward created on `/twitch` (a Twitch API rule). |

---

## How Codex was used

> **TODO (Advaith):** describe how you used OpenAI Codex in this project. The hackathon asks for this, so only list what you actually did with Codex.

## AI assistance

This project was built step by step with an AI coding assistant (**Claude Code**). The assistant:
- wrote and refactored code phase by phase
- tested each phase with automated tests and headless-browser screenshots
- debugged real issues along the way: antivirus HTTPS interception, a campus firewall blocking Twitch, and a caption-filter ordering bug the tests caught

The idea, the requirements and the feature direction came from the author. The author also handles live testing with a real Twitch channel and OBS.
