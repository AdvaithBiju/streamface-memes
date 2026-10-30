# StreamFace Memes

A Twitch tool that lets viewers trigger memes made with the streamer's own face. The face is opt-in and controlled by the streamer. A viewer types `!meme drake homework vs gaming` or redeems channel points. The app pastes a cartoony cutout of the streamer's face onto a meme template, a mod approves it, and it pops up on the stream overlay.

**Ground rules**
- Only the streamer's face, uploaded by the streamer. Viewers can't upload faces.
- Cut-and-paste cartoon style. It is not a deepfake.
- Every meme goes through mod approval before it appears on stream.
- Viewers can add only a short caption, and it has to pass a profanity and length filter.

> Built for the Codex x TwitchCon Hackathon. **Status: Phase 4 of 5** (face setup, meme editor, mod queue, OBS overlay, demo mode, live Twitch chat + channel points).

## Quick start (Windows)

```powershell
git clone https://github.com/AdvaithBiju/streamface-memes.git
cd streamface-memes
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Then:
1. Open http://127.0.0.1:5000/setup and add your face.
2. Add the overlay to OBS (see below).
3. Open http://127.0.0.1:5000/demo and http://127.0.0.1:5000/mod side by side, send `!meme drake homework vs gaming`, approve it, and watch it pop up in OBS.

On first run the app downloads MediaPipe's small face-detection model (about 230 KB) to `models/` and the built-in meme images to `templates/originals/`. If MediaPipe isn't available, it falls back to OpenCV's built-in Haar cascade automatically.

## Connect Twitch (`/twitch`)

1. **Create a Twitch app** at https://dev.twitch.tv/console/apps → **Register Your Application**:
   - **OAuth Redirect URL:** `http://localhost:5000/twitch/callback`
   - **Category:** Chat Bot
   - **Client Type:** Confidential
2. Open the app (**Manage**), copy the **Client ID**, click **New Secret**, and put both values in `.env`:
   ```
   TWITCH_CLIENT_ID=your_client_id
   TWITCH_CLIENT_SECRET=your_client_secret
   ```
3. Restart the app and open http://localhost:5000/twitch.
4. Click **Connect Twitch** and sign in as **the channel you stream on**. The status should change to "connected to #yourchannel".
5. Optional: click **Connect bot** and sign in as a second account (e.g. `yournamebot`), so the replies come from that account instead of yours.
6. If you're an Affiliate or Partner, click **Create reward** to add the "Make a Meme" channel point reward.
7. Click **Send test message to chat** to check that everything works.

There are no tokens to copy by hand. The app uses Twitch's normal sign-in page, saves the tokens in `data/twitch.json` (git-ignored), and refreshes them automatically.

How it works:
- **Live events:** chat messages and redemptions arrive over [EventSub WebSockets](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/).
- **Replies:** the bot sends them with the Helix *Send Chat Message* API.
- **Channel points:**
  - Points are refunded automatically if a meme is refused (unknown template, filtered caption, cooldown, full queue) or rejected by a mod.
  - A redemption is marked fulfilled when a mod approves the meme.
  - This only works for the reward created on this page. Twitch only lets an app manage rewards it created.

**Network note:** some school and office networks block Twitch's live connection. If `/twitch` says the connection was "redirected", try another network, like home Wi-Fi or a phone hotspot.

## Add the overlay to OBS

1. In OBS, go to **Sources → + → Browser**.
2. Set **URL** to `http://127.0.0.1:5000/overlay`, **Width** to `1920` and **Height** to `1080`. Use your canvas size if it's different.
3. Leave the background transparent (OBS's default custom CSS is fine) and click OK.

Approved memes pop in with the requester's name, stay for `OVERLAY_SECONDS` (default 8), then slide out. If several are approved at once, they queue up. The overlay also picks up anything approved while OBS was closed.

URL options:
- `?pos=left`, `?pos=right` or `?pos=center` (the default) sets where memes appear.
- `?seconds=10` overrides how long each meme stays.
- `?preview=1` adds a checkerboard background, for viewing the overlay in a normal browser tab.

## Mod queue (`/mod`)

Every viewer meme lands here first. Mods see the image, who asked for it, where it came from (chat, channel points or demo) and the caption.
- **Approve** sends a meme to the overlay. **Reject** drops it.
- Keyboard: <kbd>A</kbd> approves and <kbd>R</kbd> rejects the oldest meme.
- **Recent decisions** lists past memes, with **Replay** to show an approved meme again.
- Set your name in **Mod name** so the history shows who decided each meme.

The page updates live over Socket.IO.

## Chat commands

| Command | What it does |
|---|---|
| `!memes` | Lists the available templates |
| `!meme <name> <caption>` | Makes a meme, e.g. `!meme drake homework vs gaming` |

- **Multiple captions:** split them with `vs` or `|`, e.g. `!meme distracted new game | me | my backlog`.
- **Channel points:** the "Make a Meme" reward takes the same text without `!meme`, e.g. `twobuttons stay on stream | touch grass`.
- **Template names:** chat can type any part of a template's id or name, so `!meme roll` finds Roll Safe.

Guard rails, all set in `.env` (Twitch also adds a 15 s global cooldown on the reward):
- **`COOLDOWN_SECONDS`:** per-viewer cooldown (default 60).
- **`QUEUE_LIMIT`:** the most memes that can wait for approval at once (default 10).
- **`CAPTION_MAX_LENGTH`:** the longest caption allowed (default 80 characters).

Captions with links, @mentions or profanity are refused. The bot tells the viewer why, and replies again when their meme is queued and when it's approved.

## Demo mode (`/demo`)

Demo mode lets you test everything without Twitch. You can:
- type chat as any viewer, including random viewers via 🎲
- use the quick buttons for common commands and filter tests
- simulate a channel point redemption
- reset cooldowns
- watch a live overlay preview

Bot replies appear in the fake chat. Set `DEMO_MODE=false` in `.env` to turn the page off when you go live.

## Meme editor (`/editor`)

1. **Pick a meme**
   - **Templates:** 8 classic memes (Drake, Expanding Brain, This Is Fine, Change My Mind, Distracted Boyfriend, Two Buttons, Hide the Pain Harold, Roll Safe), plus any you uploaded or saved. Their face slots and caption boxes are already lined up with the real faces, so your face lands in the right place.
   - **Popular:** the top 100 meme templates from [Imgflip's public API](https://imgflip.com/api), the same source many GitHub meme generators use. Click one to import it.
   - **Upload:** use any meme image of your own.
2. **Add layers:** click your face to drop it onto the meme, and use **+ Add text** for captions.
3. **Adjust:**
   - Drag a face or caption to move it.
   - Drag the corner handle to resize. Faces keep their shape unless you untick *Lock aspect ratio*.
   - Drag the top handle to rotate. Hold Shift to snap to 15°.
   - Arrow keys nudge the selected item.
   - You can also flip a face, change its colour match, and set the text colours, outline and ALL CAPS.
4. **Export:**
   - Pick an output width to resize the whole meme.
   - **Generate meme** saves a PNG to `generated/`.
   - **Send to stream** puts your own meme straight onto the overlay. It skips the mod queue, since it's yours.
   - **Save as template** stores where your faces and captions sit, so chat can use that layout with `!meme <name>`.

Text auto-shrinks to fit its box, in the classic white Impact style with a black outline. The server-side renderer (`app/meme.py`) uses the same layout rules as the browser preview, so the PNG looks the same as the editor.

The meme images themselves are copyrighted, so they aren't in this repo. `templates/templates.json` holds the image URL and the face and caption positions. The app downloads the originals from Imgflip into `templates/originals/` the first time it starts, and that folder is git-ignored. If a download fails (for example when you're offline), that template stays hidden until the next start.

## Project layout

```
app/
  __init__.py      Flask app factory
  config.py        settings + .env loading
  db.py            SQLite (data/streamface.db)
  face.py          face detection + oval cutout
  meme.py          meme renderer (faces + captions -> PNG)
  memetemplates.py template registry (built-in + your own)
  imgflip.py       popular templates from Imgflip
  pipeline.py      request -> filter/cooldown -> render -> approve -> overlay
  commands.py      !meme / !memes / channel point handling
  filters.py       caption filter (length, links, profanity)
  extensions.py    Socket.IO
  twitch.py        Twitch sign-in, EventSub WebSocket, chat replies, redemptions
  net.py           shared HTTPS settings
  routes/setup.py  /setup page + /api/faces
  routes/editor.py /editor page, templates, render API
  routes/stream.py /mod, /overlay, /demo pages and APIs
  routes/twitch.py /twitch page, sign-in callback, reward creation
  pages/           HTML pages (Flask templates)
  static/          CSS / JS
templates/         templates.json (built-in template layouts)
templates/originals/  downloaded original meme images (git-ignored)
templates/user/    your uploaded/imported/saved templates (git-ignored)
generated/         finished memes (git-ignored)
data/              face cutouts + DB (git-ignored, stays on your machine)
run.py
```

## Roadmap

- [x] Phase 1: project structure, face upload or webcam snapshot, cutout on `/setup`
- [x] Phase 2: `templates.json`, meme generator, and the drag-and-drop editor with uploads and popular templates
- [x] Phase 3: mod dashboard and OBS overlay with Socket.IO, plus demo mode
- [x] Phase 4: Twitch `!meme` chat command and EventSub channel point redemptions
- [ ] Phase 5: polish, animations, full docs, Meme of the Stream voting
