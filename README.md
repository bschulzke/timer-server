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

Update: merging to `main` deploys automatically (see "Automatic deploys"). By hand: `cd ~/timer-server && git pull && docker compose up -d --build`.
Games survive the rebuild (they live in a Docker volume named after the folder, so keep the folder name).
Logs: `docker compose logs -f timer`. Stop: `docker compose down` (add `-v` to also erase saved games and certificates).

The Caddyfile also redirects tinytabletops.com and www to the timer, as a temporary (302) redirect.
Delete that block once the domain gets its own site.

## Automatic deploys
Merging to `main` updates the live site. `.github/workflows/deploy.yml` builds `main` on GitHub's machines,
pushes it to `ghcr.io/bschulzke/timer-server`, and sends `live <sha> <digest>` through the same locked-down
SSH key and script as the previews. On the droplet the script checks the commit is on `main` and the image says
it was built from it, checks out that commit in `/root/timer-server` (so compose and Caddy changes come along),
switches the `timer` service to that exact image, and waits until it answers. Saved games carry over.
Caddy is restarted only when the Caddyfile changed.

To roll back, open the Actions tab, find the deploy for the commit you want, and re-run it. You can still
deploy by hand with `git pull && docker compose up -d --build`.

The deploy script itself is not updated by deploys: changes to `deploy/preview.sh` take effect only when you
re-run its `install` line on the droplet, so nothing merged can quietly change what the deploy key may do.

## PR previews
Every pull request from a branch in this repo gets its own copy of the app at
`https://<PR number>.preview.tinytabletops.com`, posted as a comment on the PR, updated on every push and
removed when the PR closes. Previews keep no saved data and never touch the live site. At most three run at once.

How it fits together:
- `.github/workflows/preview.yml` builds the PR **on GitHub's machines** and pushes the image to
  `ghcr.io/bschulzke/timer-server`. PR code never runs on the droplet during a build.
- It then SSHes to the droplet as `deploy` and sends `deploy <pr> <sha> <image digest>` (or `remove <pr>`).
  That key can only run `sudo timer-preview` (a forced command), and `deploy` has no other rights: no shell,
  no Docker access, one sudo rule for that one root-owned script.
- `deploy/preview.sh` checks its input, pulls exactly that image by digest from that one registry address,
  checks the image says it was built from that commit, and runs it locked down: as an unprivileged user, all
  Linux capabilities dropped, no privilege escalation, read-only filesystem, memory/CPU/process limits, no
  host folders or Docker socket, on its own `timer-previews` network that the live site isn't on.
- Caddy is on both networks. It routes `<n>.preview.tinytabletops.com` to `timer-pr-<n>` and gets a
  certificate for a name the first time it's visited, but only names listed in `/srv/previews/allowed`.

One-time setup (droplet, as root):

    # DNS first: an A record with host *.preview pointing at the droplet
    cd ~/timer-server && git pull
    adduser --disabled-password --gecos "" deploy
    mkdir -p /srv/previews/allowed
    install -o root -g root -m 755 deploy/preview.sh /usr/local/bin/timer-preview
    printf '%s\n' 'Defaults!/usr/local/bin/timer-preview env_keep += "SSH_ORIGINAL_COMMAND"' \
      'deploy ALL=(root) NOPASSWD: /usr/local/bin/timer-preview' > /etc/sudoers.d/timer-preview
    chmod 440 /etc/sudoers.d/timer-preview && visudo -cf /etc/sudoers.d/timer-preview
    ssh-keygen -t ed25519 -N "" -C github-preview -f /root/preview-key
    install -d -o deploy -m 700 /home/deploy/.ssh
    echo "command=\"sudo -n /usr/local/bin/timer-preview\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $(cat /root/preview-key.pub)" > /home/deploy/.ssh/authorized_keys
    chown deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
    docker compose up -d --build

Then add repository secrets on GitHub: `PREVIEW_HOST` (the droplet's IP), `PREVIEW_SSH_KEY` (the contents of
`/root/preview-key`), and optionally `PREVIEW_KNOWN_HOSTS` (the output of `ssh-keyscan -t ed25519 <ip>`).
Delete `/root/preview-key` from the droplet once the secret is saved. After the first preview build, make the
`timer-server` package public on GitHub (Packages → timer-server → Package settings → Change visibility), so
the droplet can pull it. `sudo timer-preview list` shows running previews. If `deploy/preview.sh` changes,
re-run the `install` line.

## Settings (environment variables on the `timer` service)
`MAX_AGE_HOURS` (default 72), `MAX_GAMES` (default 2000), `PORT`, `DATA_FILE`.

## Files
- `server.mjs`: the server. `public/index.html`: the timer page. `public/bg/`: backdrops.
- The page works in both places. If the server served it, it uses the server. Otherwise it uses the Claude artifact's database.
