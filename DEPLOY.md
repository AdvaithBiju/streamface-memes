# Putting StreamFace online

Three free services, no credit card:

| Piece | Where | What it does |
|---|---|---|
| Backend | **Render** (Docker) | The Python app: Twitch chat bot, meme rendering, OBS overlay, streamer pages |
| Database | **Neon** (Postgres) | Memes, votes, and copies of your face photos and Twitch tokens |
| Viewers' site | **Vercel** (`web/user`) | Viewers sign in with Twitch and make memes |
| Mods' site | **Vercel** (`web/mod`) | You and your Twitch mods approve or reject memes and run voting |

Render's free server sleeps after 15 minutes without visitors and takes about a
minute to wake up. While OBS has the overlay open it keeps the server awake, so
it stays up for the whole stream. Its disk is wiped when it restarts, which is
why everything is also kept in Neon.

## 1. Database: Neon

1. Sign up at **neon.tech** and create a project (any name, nearest region).
2. On the dashboard, click **Connect** and copy the connection string. It looks like
   `postgresql://user:password@ep-something.neon.tech/neondb?sslmode=require`.

## 2. Backend: Render

1. Sign up at **render.com** with your GitHub account.
2. Click **New → Blueprint**, pick the `streamface-memes` repo, then **Apply**. Render reads `render.yaml`.
3. It asks for the secret values:
   - `DATABASE_URL`: the Neon string from step 1
   - `ADMIN_PASSWORD`: a password you choose, for your streamer pages
   - `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`: from your Twitch developer app
   - `USER_SITE_URL` and `MOD_SITE_URL`: leave these blank for now (step 4 fills them in)
   - `MOD_LOGINS`: optional, extra Twitch usernames allowed on the mod site, comma separated
4. The first build takes 5 to 10 minutes. When it's live, open the service URL.
   If it isn't `https://streamface-memes.onrender.com`, set `PUBLIC_URL` to your real
   URL under **Environment**, and change the address in `web/user/config.js` and
   `web/mod/config.js` to match.

## 3. Twitch developer console

Open your app at **dev.twitch.tv/console**, click **Manage**, and add these OAuth
Redirect URLs (click **Add** after each), then **Save**:

```
https://streamface-memes.onrender.com/twitch/callback
https://streamface-memes.onrender.com/auth/callback
http://localhost:5000/auth/callback
```

Use your real Render URL if it's different. Keep the existing
`http://localhost:5000/twitch/callback`.

## 4. The two sites: Vercel

Do this twice, once per site:

1. Sign up at **vercel.com** with GitHub, then **Add New → Project** and import `streamface-memes`.
2. **Root Directory**: `web/user` for the viewers' site, `web/mod` for the mods' site.
3. **Framework Preset**: Other. No build command. Click **Deploy**.
4. Copy the site's address, e.g. `https://streamface-memes.vercel.app`.

Then go back to Render → **Environment** and set:

- `USER_SITE_URL` = the viewers' site address
- `MOD_SITE_URL` = the mods' site address

No trailing slash. Render restarts with the new settings.

## 5. Set up the online copy

The online server has its own data, separate from your PC. Open
`https://<your-render-url>/setup` and log in with any username and your
`ADMIN_PASSWORD`. Then:

1. **/setup**: upload your face photos again.
2. **/twitch**: click **Connect** for the streamer account. This also grants
   `moderation:read`, which lets the mod site check who your mods are.
3. In OBS, change the Browser Source URL to `https://<your-render-url>/overlay`.

Don't keep the app on your PC connected to Twitch at the same time, or every
chat command gets answered twice.

## Checking it works

- Viewers' site: sign in, make a meme, send it.
- Mods' site: sign in as yourself. The meme should be waiting; approve it and it plays in OBS.
- A viewer who isn't a mod gets "isn't a mod of this channel" on the mods' site.
