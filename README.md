# Shenan-Again Loop Timer: server

One small Node server. It serves the timer page and keeps shared games in memory, saved to a file so a restart
doesn't lose them. Devices connect over one WebSocket (`/ws`). Idle games are deleted after 72 hours.

## What the server enforces
- Only the GM can change the clock. A player can take over only after the GM has been gone for 25 seconds
  (the page waits 30), and the original GM can always take it back.
- Timestamps are limited to 120 characters and 500 per game. Every field from the page is checked.
- Each connection is rate limited. Messages over 8 KB are refused.
- Devices sync to the server's clock, so a phone with a wrong clock still counts down correctly.

## Music
Music plays on one device only: the GM's by default, or whichever device last tapped "Play music here"
(in the Sound dialog). Cool Vibes plays whenever the clock isn't running. Each loop opens on the next track
of the rotation (Covert Affair, Spy Glass, Fast Talkin, Bossa Antigua). In the last three minutes the music
speeds up and a clock ticks; both pick up again in the last minute. At the end of a loop the music drops
under the alarm, then Cool Vibes fades back in. Songs change with a short dip: the old one fades out over its last few seconds, then the next fades in.
Getting out or getting caught plays a short sting first.
The alarm and chimes are on by default only on the music device; anyone can turn them on for their own.

Tracks live in `public/music/` (re-encoded to 128 kbps). They're by Kevin MacLeod (incompetech.com),
licensed under Creative Commons: By Attribution 4.0. The credit is shown in the Sound dialog.

## Run it on your computer
    npm install
    npm start            # http://localhost:3000
    npm test             # protocol checks
    python3 e2e.py       # two real browsers (needs playwright)
    python3 e2e_music.py # music: hand-off, rotation, final-minutes effect (about 2 minutes)

## Deploy to the droplet
First time:
1. DNS: `A` records for `timer`, `@` and `www` on tinytabletops.com, all pointing at the droplet's IP.
2. Nothing else on the droplet may use ports 80 and 443 (`docker ps`, PORTS column).
3. On the droplet:

       git clone <repo url> ~/timer-server
       cd ~/timer-server
       cp .env.example .env
       docker compose up -d --build

4. Open `https://timer.tinytabletops.com`. Caddy fetches the certificates on its own.

Update: push from your PC, then on the droplet `cd ~/timer-server && git pull && docker compose up -d --build`.
Games survive the rebuild (they live in a Docker volume named after the folder, so keep the folder name).
Logs: `docker compose logs -f timer`. Stop: `docker compose down` (add `-v` to also erase saved games and certificates).

The Caddyfile also redirects tinytabletops.com and www to the timer, as a temporary (302) redirect.
Delete that block once the domain gets its own site.

## Settings (environment variables on the `timer` service)
`MAX_AGE_HOURS` (default 72), `MAX_GAMES` (default 2000), `PORT`, `DATA_FILE`.

## Files
- `server.mjs`: the server. `public/index.html`: the timer page. `public/bg/`: backdrops.
- The page works in both places. If the server served it, it uses the server. Otherwise it uses the Claude artifact's database.
