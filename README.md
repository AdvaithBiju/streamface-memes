# StreamFace Memes

A Twitch tool that lets viewers trigger memes made with the streamer's own face. The face is opt-in and controlled by the streamer. A viewer types `!meme drake homework vs gaming` or redeems channel points. The app pastes a cartoony cutout of the streamer's face onto a meme template, a mod approves it, and it pops up on the stream overlay.

**Ground rules**
- Only the streamer's face, uploaded by the streamer. Viewers can't upload faces.
- Cut-and-paste cartoon style. It is not a deepfake.
- Every meme goes through mod approval before it appears on stream.
- Viewers can add only a short caption, and it has to pass a profanity and length filter.

> Built for the Codex x TwitchCon Hackathon. **Status: Phase 2 of 5** (face setup + meme editor). The full setup, Twitch and OBS guide comes in Phase 5.

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

Open http://127.0.0.1:5000/setup to add your face, then http://127.0.0.1:5000/editor to make memes.

On first run the app downloads MediaPipe's small face-detection model (about 230 KB) to `models/` and the built-in meme images to `templates/originals/`. If MediaPipe isn't available, it falls back to OpenCV's built-in Haar cascade automatically.

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
   - **Save as template** stores where your faces and captions sit, so chat can use that layout later with `!meme <name>`.

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
  routes/setup.py  /setup page + /api/faces
  routes/editor.py /editor page, templates, render API
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
- [ ] Phase 3: mod dashboard and OBS overlay with Socket.IO, plus demo mode
- [ ] Phase 4: Twitch `!meme` chat command and EventSub channel point redemptions
- [ ] Phase 5: polish, animations, full docs, Meme of the Stream voting
