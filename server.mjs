// Shenan-Again Loop Timer server.
// Serves the page and keeps shared games in memory, saved to a JSON file so a restart doesn't lose live games.
// Clients talk to it over one WebSocket at /ws. See the protocol notes next to handle().
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, 'public');
const PORT = +process.env.PORT || 3000;
const DATA_FILE = process.env.DATA_FILE || path.join(HERE, 'data', 'games.json');
const MAX_AGE = (+process.env.MAX_AGE_HOURS || 72) * 3600e3;   // idle games are deleted after this long
const MAX_GAMES = +process.env.MAX_GAMES || 2000;
const MAX_MARKS = 500;
const GRACE = +process.env.GRACE_MS || 25000;                                           // a GM absent this long can be replaced (the page waits 30 s)
const HOUR = 3600;

const PHASES = ['ready', 'running', 'paused', 'caught', 'won'];
const BGS = ['grid', 'vault', 'circus', 'yacht', 'iss', 'street'];
const CODE_RE = /^[A-Z0-9]{4}$/;
const ID_RE = /^[A-Za-z0-9_-]{1,40}$/;

/* ---------- state ---------- */
// games: code -> {game, marks: Map(id -> mark), touched}
const games = new Map();
// presence: code -> Map(socket -> deviceId); lastHostSeen: code -> ms
const rooms = new Map();
const hostSeen = new Map();

function load() {
  try {
    const raw = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
    for (const [code, g] of Object.entries(raw)) {
      games.set(code, { game: g.game, marks: new Map(Object.entries(g.marks || {})), touched: g.touched || Date.now() });
    }
  } catch { /* first run */ }
}
let saveTimer = null;
function saveSoon() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    const out = {};
    for (const [code, g] of games) out[code] = { game: g.game, marks: Object.fromEntries(g.marks), touched: g.touched };
    try {
      fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
      fs.writeFileSync(DATA_FILE + '.tmp', JSON.stringify(out));
      fs.renameSync(DATA_FILE + '.tmp', DATA_FILE);
    } catch (e) { console.error('save failed', e.message); }
  }, 1500);
}

/* ---------- validation: never trust the page ---------- */
const int = (v, lo, hi, d) => { v = Math.round(+v); return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d; };
function cleanGame(g) {
  if (!g || typeof g !== 'object') return null;
  const o = {
    loop: int(g.loop, 1, 3, 1),
    phase: PHASES.includes(g.phase) ? g.phase : 'ready',
    remaining: int(g.remaining, 0, HOUR * 1000, HOUR * 1000),
    deadline: typeof g.deadline === 'number' && Number.isFinite(g.deadline) ? g.deadline : null,
    speed: [1, 10, 60].includes(g.speed) ? g.speed : 1,
    won: g.won == null ? null : int(g.won, 0, HOUR, 0),
    bg: BGS.includes(g.bg) ? g.bg : 'vault',
    hostId: typeof g.hostId === 'string' && ID_RE.test(g.hostId) ? g.hostId : null,
    origHost: typeof g.origHost === 'string' && ID_RE.test(g.origHost) ? g.origHost : null,
    rev: int(g.rev, 0, 1e9, 0),
    dj: typeof g.dj === 'string' && ID_RE.test(g.dj) ? g.dj : null,
    gid: typeof g.gid === 'string' && ID_RE.test(g.gid) ? g.gid : null,   // changes with every new game
    luck: g.luck === true,                                             // Luck Dice counter on (GM's choice)
    dice: int(g.dice, 0, 20, 20),                                      // Luck Dice left this loop
  };
  return o;
}
function cleanMark(m, id) {
  if (!m || typeof m !== 'object' || !ID_RE.test(String(id))) return null;
  return { t: int(m.t, 0, HOUR, 0), loop: int(m.loop, 0, 3, 1), note: String(m.note ?? '').replace(/\n/g, ' ').slice(0, 120) };
}

/* ---------- presence ---------- */
function peersOf(code) {
  const r = rooms.get(code);
  return r ? [...new Set(r.values())] : [];
}
function hostPresent(code) {
  const g = games.get(code);
  return !!g && peersOf(code).includes(g.game.hostId);
}
function trackHost(code) {
  if (hostPresent(code)) hostSeen.set(code, Date.now());
}
function sendPeers(code) {
  trackHost(code);
  const msg = JSON.stringify({ ev: 'peers', code, list: peersOf(code) });
  for (const ws of watchers(code)) ws.send(msg);
}

/* ---------- sockets ---------- */
const wsServer = new WebSocketServer({ noServer: true, maxPayload: 8 * 1024 });
const watching = new Map();            // code -> Set(ws)
const watchers = (code) => watching.get(code) || [];
function addWatch(ws, code) {
  if (!watching.has(code)) watching.set(code, new Set());
  watching.get(code).add(ws);
  ws.watch.add(code);
}
function dropWatch(ws, code) {
  watching.get(code)?.delete(ws);
  ws.watch.delete(code);
  const r = rooms.get(code);
  if (r) { r.delete(ws); if (!r.size) rooms.delete(code); }
  sendPeers(code);
}
const reply = (ws, rid, body) => ws.send(JSON.stringify({ rid, ...body }));
const marksList = (g) => [...g.marks].map(([id, m]) => ({ id, ...m }));

function broadcastGame(code, except) {
  const g = games.get(code);
  const msg = JSON.stringify({ ev: 'game', code, game: g ? g.game : null });
  for (const ws of watchers(code)) if (ws !== except) ws.send(msg);
}
function broadcastMarks(code) {
  const g = games.get(code);
  const msg = JSON.stringify({ ev: 'marks', code, marks: g ? marksList(g) : [] });
  for (const ws of watchers(code)) ws.send(msg);
}

// May this device replace the stored clock? The GM always can. Anyone else can only take over
// when the GM has been gone a while (or there is no GM), and must say so by naming themselves as the new GM.
function mayWriteGame(code, device, next) {
  const cur = games.get(code);
  if (!cur) return next.hostId === device;                         // creating a game makes you its GM
  const host = cur.game.hostId;
  if (host === device) return true;
  if (next.hostId !== device) return false;
  if (!host) return true;
  if (cur.game.origHost === device) return true;                   // the original GM reclaiming the clock
  if (hostPresent(code)) return false;
  return Date.now() - (hostSeen.get(code) || 0) > GRACE;
}

/*
  Protocol. Every request carries rid and gets {rid, ok:true, data?} or {rid, ok:false, code}.
    hello  {device}                   -> {ok, now}             (now = server clock, ms)
    read   {code}                     -> {ok, data: game|null}
    write  {code, game}               -> {ok}
    wmark  {code, id, mark}           -> {ok}
    dmark  {code, id}                 -> {ok}
    watch  {code}                     -> {ok}; then pushes {ev:'game'} and {ev:'marks'} now and on every change
    unwatch{code}
    join   {code}                     -> {ok}; adds this device to the game's presence list, pushed as {ev:'peers'}
    dj     {code}                     -> {ok}; makes this device the one that plays the music
    luck   {code, delta}              -> {ok}; spends (delta < 0, anyone) or gives back (delta > 0, GM only)
                                         Luck Dice, while the counter is on
*/
function handle(ws, m) {
  const { op, rid } = m;
  const code = typeof m.code === 'string' ? m.code.toUpperCase() : '';
  const bad = (c = 'invalid_argument') => reply(ws, rid, { ok: false, code: c });

  if (op === 'hello') {
    if (typeof m.device !== 'string' || !ID_RE.test(m.device)) return bad();
    ws.device = m.device;
    return reply(ws, rid, { ok: true, now: Date.now() });
  }
  if (!ws.device) return bad('not_granted');
  if (!CODE_RE.test(code)) return bad();

  switch (op) {
    case 'read': {
      const g = games.get(code);
      return reply(ws, rid, { ok: true, data: g ? g.game : null });
    }
    case 'watch': {
      addWatch(ws, code);
      reply(ws, rid, { ok: true });
      const g = games.get(code);
      ws.send(JSON.stringify({ ev: 'game', code, game: g ? g.game : null }));
      ws.send(JSON.stringify({ ev: 'marks', code, marks: g ? marksList(g) : [] }));
      return;
    }
    case 'unwatch': dropWatch(ws, code); return reply(ws, rid, { ok: true });
    case 'join': {
      if (!games.has(code)) return bad('not_found');
      addWatch(ws, code);
      if (!rooms.has(code)) rooms.set(code, new Map());
      rooms.get(code).set(ws, ws.device);
      reply(ws, rid, { ok: true });
      return sendPeers(code);
    }
    case 'write': {
      const next = cleanGame(m.game);
      if (!next) return bad();
      if (!games.has(code) && games.size >= MAX_GAMES) return bad('full');
      if (!mayWriteGame(code, ws.device, next)) {
        reply(ws, rid, { ok: false, code: 'rejected' });
        const g = games.get(code);                                     // put this device back in step
        if (g) ws.send(JSON.stringify({ ev: 'game', code, game: g.game }));
        return;
      }
      const cur = games.get(code);
      // The music device is set only through 'dj'; a clock write never moves it.
      next.dj = cur ? (cur.game.dj || cur.game.hostId) : next.hostId;
      // Luck Dice change only through 'luck', so a clock write keeps the current count.
      // A new loop or a new game starts again from 20.
      next.dice = cur && cur.game.loop === next.loop && cur.game.gid === next.gid ? cur.game.dice : 20;
      if (cur) { cur.game = { ...next, updatedAt: Date.now() }; cur.touched = Date.now(); }
      else games.set(code, { game: { ...next, updatedAt: Date.now() }, marks: new Map(), touched: Date.now() });
      if (ws.device === next.hostId) hostSeen.set(code, Date.now());     // the GM just proved they are here
      trackHost(code); saveSoon();
      reply(ws, rid, { ok: true });
      return broadcastGame(code, null);
    }
    case 'dj': {                                                       // "Play music here": any device in the game
      const g = games.get(code);
      if (!g) return bad('not_found');
      g.game = { ...g.game, dj: ws.device, updatedAt: Date.now() }; g.touched = Date.now(); saveSoon();
      reply(ws, rid, { ok: true });
      return broadcastGame(code, null);
    }
    case 'luck': {
      const g = games.get(code);
      if (!g) return bad('not_found');
      const delta = Math.round(+m.delta);
      if (!Number.isFinite(delta) || delta === 0 || Math.abs(delta) > 20) return bad();
      if (!g.game.luck) return bad('failed_precondition');
      g.game = { ...g.game, dice: Math.min(20, Math.max(0, g.game.dice + delta)), updatedAt: Date.now() };
      g.touched = Date.now(); saveSoon();
      reply(ws, rid, { ok: true });
      return broadcastGame(code, null);
    }
    case 'wmark': {
      const g = games.get(code);
      if (!g) return bad('not_found');
      const mark = cleanMark(m.mark, m.id);
      if (!mark) return bad();
      if (!g.marks.has(m.id) && g.marks.size >= MAX_MARKS) return bad('full');
      g.marks.set(m.id, mark); g.touched = Date.now(); saveSoon();
      reply(ws, rid, { ok: true });
      return broadcastMarks(code);
    }
    case 'dmark': {
      const g = games.get(code);
      if (!g) return reply(ws, rid, { ok: true });
      g.marks.delete(String(m.id)); g.touched = Date.now(); saveSoon();
      reply(ws, rid, { ok: true });
      return broadcastMarks(code);
    }
    default: return bad();
  }
}

wsServer.on('connection', (ws) => {
  ws.watch = new Set(); ws.device = null; ws.alive = true;
  let bucket = 40, last = Date.now();                                  // about 20 messages a second, bursts of 40
  ws.on('pong', () => { ws.alive = true; });
  ws.on('message', (data) => {
    const now = Date.now();
    bucket = Math.min(40, bucket + (now - last) / 50); last = now;
    if (--bucket < 0) return ws.close(1008, 'slow down');
    let m; try { m = JSON.parse(data.toString()); } catch { return; }
    if (!m || typeof m !== 'object' || typeof m.op !== 'string') return;
    try { handle(ws, m); } catch (e) { console.error('handler', e); }
  });
  ws.on('close', () => { for (const c of [...ws.watch]) dropWatch(ws, c); });
});
setInterval(() => {                                                    // drop dead connections so presence stays honest
  for (const ws of wsServer.clients) {
    if (!ws.alive) { ws.terminate(); continue; }
    ws.alive = false; ws.ping();
  }
}, 15000).unref();

/* ---------- cleanup ---------- */
function sweep() {
  const cutoff = Date.now() - MAX_AGE;
  for (const [code, g] of games) {
    if (g.touched < cutoff && !(rooms.get(code)?.size)) {
      games.delete(code); hostSeen.delete(code); broadcastGame(code, null);
    }
  }
  saveSoon();
}
setInterval(sweep, 3600e3).unref();

/* ---------- static files ---------- */
const TYPES = { '.html': 'text/html; charset=utf-8', '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml',
                '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.txt': 'text/plain',
                '.mp3': 'audio/mpeg' };
function page() {
  // The page looks for this tag to know it is running against its own server.
  return fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').replace('<meta name="shenan-ws" content="">', '<meta name="shenan-ws" content="/ws">');
}
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  if (url.pathname === '/healthz') { res.writeHead(200); return res.end('ok'); }
  const headers = { 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' };
  if (url.pathname === '/' || url.pathname === '/index.html') {
    res.writeHead(200, { ...headers, 'Content-Type': TYPES['.html'], 'Cache-Control': 'no-cache' });
    return res.end(page());
  }
  const file = path.normalize(path.join(PUBLIC, decodeURIComponent(url.pathname)));
  if (!file.startsWith(PUBLIC + path.sep) || path.basename(file) === 'index.html') { res.writeHead(404); return res.end('Not found'); }
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) { res.writeHead(404); return res.end('Not found'); }
    const base = { ...headers, 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream',
                   'Cache-Control': 'public, max-age=86400', 'Accept-Ranges': 'bytes' };
    // Browsers fetch audio in pieces (byte ranges) to seek, and iPhones won't play audio without it.
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    if (m && (m[1] || m[2])) {
      let start = m[1] ? +m[1] : Math.max(0, st.size - +m[2]);
      let end = m[1] && m[2] ? Math.min(+m[2], st.size - 1) : st.size - 1;
      if (start >= st.size || start > end) {
        res.writeHead(416, { ...base, 'Content-Range': `bytes */${st.size}` }); return res.end();
      }
      res.writeHead(206, { ...base, 'Content-Range': `bytes ${start}-${end}/${st.size}`, 'Content-Length': end - start + 1 });
      if (req.method === 'HEAD') return res.end();
      return fs.createReadStream(file, { start, end }).pipe(res);
    }
    res.writeHead(200, { ...base, 'Content-Length': st.size });
    if (req.method === 'HEAD') return res.end();
    fs.createReadStream(file).pipe(res);
  });
});
server.on('upgrade', (req, socket, head) => {
  if (new URL(req.url, 'http://x').pathname !== '/ws') return socket.destroy();
  wsServer.handleUpgrade(req, socket, head, (ws) => wsServer.emit('connection', ws, req));
});

load();
server.listen(PORT, () => console.log(`timer listening on :${PORT}, ${games.size} saved games`));
const stop = () => { clearTimeout(saveTimer); saveTimer = null; saveSoon(); setTimeout(() => process.exit(0), 1800); };
process.on('SIGTERM', stop); process.on('SIGINT', stop);
