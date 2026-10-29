# StreamFace Memes

A Twitch tool that lets viewers trigger memes made with the streamer's own face. The face is opt-in and controlled by the streamer. A viewer types `!meme drake homework vs gaming` or redeems channel points. The app pastes a cartoony cutout of the streamer's face onto a meme template, a mod approves it, and it pops up on the stream overlay.

**Ground rules**
- Only the streamer's face, uploaded by the streamer. Viewers can't upload faces.
- Cut-and-paste cartoon style. It is not a deepfake.
- Every meme goes through mod approval before it appears on stream.
- Viewers can add only a short caption, and it has to pass a profanity and length filter.

> Built for the Codex x TwitchCon Hackathon. **Status: Phase 1 of 5** (face setup). The full setup, Twitch and OBS guide comes in Phase 5.

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

Open http://127.0.0.1:5000/setup.

On first run the app downloads MediaPipe's small face-detection model (about 230 KB) to `models/`. If MediaPipe isn't available, it falls back to OpenCV's built-in Haar cascade automatically.

## Project layout

```
app/
  __init__.py      Flask app factory
  config.py        settings + .env loading
  db.py            SQLite (data/streamface.db)
  face.py          face detection + oval cutout
  routes/setup.py  /setup page + /api/faces
  pages/           HTML pages (Flask templates)
  static/          CSS / JS
templates/         meme template images + templates.json (Phase 2)
generated/         finished memes (Phase 2)
data/              face cutouts + DB (git-ignored, stays on your machine)
run.py
```

## Roadmap

- [x] Phase 1: project structure, face upload or webcam snapshot, cutout on `/setup`
- [ ] Phase 2: `templates.json` and meme generator
- [ ] Phase 3: mod dashboard and OBS overlay with Socket.IO, plus demo mode
- [ ] Phase 4: Twitch `!meme` chat command and EventSub channel point redemptions
- [ ] Phase 5: polish, animations, full docs, Meme of the Stream voting
