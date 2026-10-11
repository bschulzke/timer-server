// Protocol checks against a throwaway server. Run: npm test
import { spawn } from 'node:child_process';
import WebSocket from 'ws';
import fs from 'node:fs';

const PORT = 3911, DATA = '/tmp/shenan-test-games.json';
try { fs.unlinkSync(DATA); } catch {}
const srv = spawn('node', ['server.mjs'], { env: { ...process.env, PORT, DATA_FILE: DATA, GRACE_MS: '400' }, stdio: 'inherit' });
await new Promise(r => setTimeout(r, 600));

let fails = 0;
const ok = (c, name) => { console.log((c ? 'pass ' : 'FAIL ') + name); if (!c) fails++; };

function client(device) {
  const ws = new WebSocket(`ws://localhost:${PORT}/ws`);
  const events = []; let n = 1; const pend = {};
  ws.on('message', d => { const m = JSON.parse(d); if (m.rid && pend[m.rid]) { pend[m.rid](m); delete pend[m.rid]; } else events.push(m); });
  const req = (msg) => new Promise(res => { const rid = n++; pend[rid] = res; ws.send(JSON.stringify({ ...msg, rid })); });
  return new Promise(res => ws.on('open', async () => { await req({ op: 'hello', device }); res({ ws, req, events }); }));
}
const game = (o = {}) => ({ loop: 1, phase: 'ready', remaining: 3600000, deadline: null, speed: 1, won: null, bg: 'vault', hostId: 'gm1', origHost: 'gm1', rev: 1, ...o });
const wait = ms => new Promise(r => setTimeout(r, ms));

const gm = await client('gm1'), p1 = await client('pl1');
ok((await gm.req({ op: 'write', code: 'ABCD', game: game() })).ok, 'GM creates a game');
ok((await p1.req({ op: 'write', code: 'WXYZ', game: game() })).code === 'rejected', 'creating a game as someone else\'s hostId is rejected');
ok((await p1.req({ op: 'read', code: 'ABCD' })).data.hostId === 'gm1', 'player can read it');
ok((await p1.req({ op: 'write', code: 'ABCD', game: game({ phase: 'running', rev: 2 }) })).code === 'rejected', 'player cannot change the clock');
ok((await p1.req({ op: 'read', code: 'ABCD' })).data.phase === 'ready', 'clock unchanged after rejected write');
ok((await p1.req({ op: 'write', code: 'ABCD', game: game({ hostId: 'pl1', rev: 2 }) })).code === 'rejected', 'player cannot take over while GM is not yet known absent');

await p1.req({ op: 'watch', code: 'ABCD' });
await gm.req({ op: 'join', code: 'ABCD' });
await p1.req({ op: 'join', code: 'ABCD' });
await wait(100);
ok(p1.events.some(e => e.ev === 'peers' && e.list.includes('gm1') && e.list.includes('pl1')), 'presence lists both devices');
ok((await p1.req({ op: 'write', code: 'ABCD', game: game({ hostId: 'pl1', rev: 2 }) })).code === 'rejected', 'player cannot take over while GM is present');

p1.events.length = 0;
await gm.req({ op: 'write', code: 'ABCD', game: game({ phase: 'running', deadline: Date.now() + 3600000, rev: 2 }) });
await wait(100);
ok(p1.events.some(e => e.ev === 'game' && e.game.phase === 'running'), 'player sees the GM\'s change');

ok((await p1.req({ op: 'wmark', code: 'ABCD', id: 'm1', mark: { t: 120, loop: 1, note: 'Guard changes\nshift' } })).ok, 'player adds a timestamp');
await wait(100);
const last = p1.events.filter(e => e.ev === 'marks').pop();
ok(last && last.marks.length === 1 && last.marks[0].note === 'Guard changes shift', 'timestamp broadcast and sanitized');
ok((await p1.req({ op: 'wmark', code: 'ABCD', id: 'bad id!', mark: { t: 1 } })).code === 'invalid_argument', 'bad mark id refused');
ok((await p1.req({ op: 'dmark', code: 'ABCD', id: 'm1' })).ok, 'player deletes it');

ok((await p1.req({ op: 'read', code: 'ABCD' })).data.dj === 'gm1', 'music plays on the GM device by default');
ok((await p1.req({ op: 'dj', code: 'ABCD' })).ok, 'a player can take over the music');
ok((await p1.req({ op: 'read', code: 'ABCD' })).data.dj === 'pl1', 'music device moved to the player');
await gm.req({ op: 'write', code: 'ABCD', game: game({ phase: 'paused', rev: 3, dj: 'gm1' }) });
ok((await p1.req({ op: 'read', code: 'ABCD' })).data.dj === 'pl1', 'a GM clock write does not move the music back');
await gm.req({ op: 'write', code: 'ABCD', game: game({ phase: 'paused', rev: 4, gid: 'g2' }) });
ok((await p1.req({ op: 'read', code: 'ABCD' })).data.gid === 'g2', 'the game id is kept');
await gm.req({ op: 'write', code: 'ABCD', game: game({ phase: 'paused', rev: 5, gid: 'bad id!' }) });
ok((await p1.req({ op: 'read', code: 'ABCD' })).data.gid === null, 'a malformed game id is dropped');

// Luck Dice
const rd = async () => (await p1.req({ op: 'read', code: 'ABCD' })).data;
ok((await p1.req({ op: 'luck', code: 'ABCD', delta: -3 })).code === 'failed_precondition', 'no spending while the counter is off');
await gm.req({ op: 'write', code: 'ABCD', game: game({ phase: 'paused', rev: 6, luck: true }) });
ok((await rd()).dice === 20, 'counter starts at 20');
ok((await p1.req({ op: 'luck', code: 'ABCD', delta: -3 })).ok && (await rd()).dice === 17, 'a player spends 3');
ok((await p1.req({ op: 'luck', code: 'ABCD', delta: 2 })).ok && (await rd()).dice === 19, 'a player can add dice back');
ok((await gm.req({ op: 'luck', code: 'ABCD', delta: -1 })).ok && (await rd()).dice === 18, 'the GM spends one');
await gm.req({ op: 'write', code: 'ABCD', game: game({ phase: 'running', deadline: Date.now() + 1e6, rev: 7, luck: true, dice: 20 }) });
ok((await rd()).dice === 18, 'a clock write in the same loop keeps the count');
await p1.req({ op: 'luck', code: 'ABCD', delta: -20 });
ok((await rd()).dice === 0, 'the count never goes below 0');
await gm.req({ op: 'write', code: 'ABCD', game: game({ loop: 2, phase: 'ready', rev: 8, luck: true, dice: 0 }) });
ok((await rd()).dice === 20, 'a new loop starts again from 20');
ok((await p1.req({ op: 'luck', code: 'ABCD', delta: 'x' })).code === 'invalid_argument', 'a bad amount is refused');

gm.ws.close(); await wait(100);
ok((await p1.req({ op: 'write', code: 'ABCD', game: game({ hostId: 'pl1', rev: 4 }) })).code === 'rejected', 'takeover still refused right after GM leaves');
await wait(500);
ok((await p1.req({ op: 'write', code: 'ABCD', game: game({ hostId: 'pl1', rev: 4 }) })).ok, 'takeover allowed once GM has been gone a while');
ok((await p1.req({ op: 'hello', device: 'bad id!' })).code === 'invalid_argument', 'bad device id refused');

const r1 = await fetch(`http://localhost:${PORT}/music/fast-talkin.mp3`, { headers: { Range: 'bytes=100-199' } });
ok(r1.status === 206 && r1.headers.get('content-range').startsWith('bytes 100-199/') && (await r1.arrayBuffer()).byteLength === 100, 'audio served in byte ranges');
const r2 = await fetch(`http://localhost:${PORT}/music/fast-talkin.mp3`, { method: 'HEAD' });
ok(r2.status === 200 && r2.headers.get('content-type') === 'audio/mpeg' && r2.headers.get('accept-ranges') === 'bytes', 'audio served as audio/mpeg');
ok((await fetch(`http://localhost:${PORT}/../server.mjs`)).status === 404, 'no files outside public/');

p1.ws.close(); srv.kill('SIGTERM');
await wait(2500);
const saved = JSON.parse(fs.readFileSync(DATA, 'utf8'));
ok(saved.ABCD && saved.ABCD.game.hostId === 'pl1', 'games saved to disk');
console.log(fails ? `${fails} failed` : 'all passed');
process.exit(fails ? 1 : 0);
