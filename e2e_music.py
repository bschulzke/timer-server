# Music checks in two real browsers. Run: python3 e2e_music.py
import subprocess, time, os, re
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PORT='3916', DATA_FILE='/tmp/shenan-music.json')
try: os.remove(env['DATA_FILE'])
except OSError: pass
srv = subprocess.Popen(['node', 'server.mjs'], env=env, cwd=HERE); time.sleep(1)
URL = 'http://localhost:3916/'
bad = 0
def tool(pg, sel):
    # Phones keep the tool buttons in the three-dot menu.
    if pg.is_visible('#btn-menu'): pg.click('#btn-menu'); pg.wait_for_timeout(150)
    pg.click(sel)
def check(c, name):
    global bad
    print(('pass ' if c else 'FAIL ') + name); bad += 0 if c else 1
M = lambda pg: pg.evaluate("() => { const m = window.__music; return m && {on: m.on, mode: m.mode, src: m.src, rate: +m.rateTo.toFixed(2), playing: !!(m.el && !m.el.paused), fade: m.fade ? +m.fade.gain.value.toFixed(2) : null} }")
try:
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        dev = p.devices['iPhone 13']
        gm = b.new_context(**dev).new_page(); pl = b.new_context(**dev).new_page()
        for n, pg in (('gm', gm), ('pl', pl)): pg.on('pageerror', lambda e, n=n: print(n, 'page error', e))
        gm.goto(URL + '?test'); gm.wait_for_selector('[data-land=host]:not([disabled])')
        gm.click('[data-land=host]'); gm.wait_for_timeout(2500)
        m = M(gm); print('  gm after host:', m)
        check(m['on'] and m['mode'] == 'lobby' and 'cool-vibes' in m['src'] and m['playing'], 'GM device starts Cool Vibes on hosting')
        tool(gm, '#btn-share'); gm.wait_for_timeout(300)
        code = re.search(r'#([A-Z0-9]{4})', gm.inner_text('#panel-share')).group(1)
        gm.select_option('#speed', '60'); gm.click('#panel-share .panel-x')

        pl.goto(URL + '?test#' + code); pl.wait_for_timeout(1500); pl.click('body', position={'x': 5, 'y': 300}); pl.wait_for_timeout(800)
        check(not M(pl)['on'], 'player device stays quiet')
        st = pl.evaluate("() => ({src: window.__music.el ? window.__music.el.getAttribute('src') : null})")
        check(not st['src'], 'player device holds no track, so its lock screen can\'t start music')
        pl.evaluate("() => window.__music.el && window.__music.el.play().catch(()=>{})"); pl.wait_for_timeout(500)
        check(not M(pl)['playing'], 'starting the track on a player device is refused')
        check(pl.evaluate("() => document.getElementById('chip').tagName") == 'SPAN', 'game status is plain text, not a button')
        pl.click('#btn-menu'); pl.wait_for_timeout(200)
        items = [x.inner_text().strip() for x in pl.query_selector_all('#tools .btn') if x.is_visible()]
        print('  player menu:', items)
        check(items[:2] == ['SHARE GAME', 'LEAVE GAME'] and 'NEW GAME' not in items, 'player menu: share and leave, no new game')
        pl.click('#menu-leave'); pl.wait_for_timeout(300)
        check(pl.query_selector('[data-act=leave-yes]') is not None, 'leaving asks to confirm')
        pl.click('[data-act=cancel]'); pl.wait_for_timeout(200)
        check(pl.query_selector('#chip:not([hidden])') is not None, 'cancel keeps you in the game')
        tool(pl, '#btn-sound'); pl.wait_for_timeout(300)
        check(not pl.is_checked('#snd-chimes'), 'chimes default off on a non-music device')
        check('GM’s device' in pl.inner_text('#snd-dj'), 'player sees the music is on the GM device')
        pl.screenshot(path='/tmp/snd_player.png'); pl.click('#panel-sound .panel-x')
        tool(gm, '#btn-sound'); gm.wait_for_timeout(300)
        check(gm.is_checked('#snd-chimes'), 'chimes default on for the music device')
        gm.screenshot(path='/tmp/snd_gm.png'); gm.click('#panel-sound .panel-x')

        gm.click('#btn-menu'); gm.wait_for_timeout(200)
        items = [x.inner_text().strip() for x in gm.query_selector_all('#tools .btn') if x.is_visible()]
        print('  GM menu:', items)
        check(items[:3] == ['SHARE GAME', 'NEW GAME', 'LEAVE GAME'], 'GM menu: share, new game, leave')
        gm.click('#btn-menu'); gm.wait_for_timeout(200)
        gm.click('[data-act=start]'); gm.wait_for_timeout(3000)
        m = M(gm); print('  gm running:', m)
        check(m['mode'] == 'loop' and 'covert-affair' in m['src'], 'loop 1 opens on Covert Affair')
        gm.click('[data-act=pause]'); gm.wait_for_timeout(800)
        check(M(gm)['mode'] == 'loop' and 'covert-affair' in M(gm)['src'], 'pausing keeps the same track')
        gm.click('[data-act=start]')
        # 60x speed: the final three minutes arrive after ~57 s of real time
        gm.wait_for_function("() => { const s = document.getElementById('readout').getAttribute('aria-label'); return /^0[0-2]:/.test(s); }", timeout=90000)
        gm.wait_for_timeout(1700)
        check(M(gm)['rate'] == 1.08, 'speeds up in the last three minutes')
        gm.wait_for_function("() => /^00:/.test(document.getElementById('readout').getAttribute('aria-label'))", timeout=10000)
        gm.wait_for_timeout(500)
        check(M(gm)['rate'] == 1.15, 'speeds up again in the last minute')
        gm.wait_for_function("() => /loop 2 of 3/.test(document.getElementById('readout').getAttribute('aria-label'))", timeout=10000)
        gm.wait_for_timeout(700)
        m = M(gm); print('  gm at reset:', m)
        check(m['mode'] == 'lobby-pending' and m['rate'] == 1, 'loop end: music ducks and heads back to the between-loops track')
        gm.wait_for_timeout(5500)
        m = M(gm); print('  gm after reset:', m)
        check(m['mode'] == 'lobby' and 'cool-vibes' in m['src'], 'Cool Vibes back between loops')
        gm.evaluate("() => { const e = window.__music.el; e.currentTime = e.duration - 5; }")
        gm.wait_for_timeout(6500)
        t = gm.evaluate("() => window.__music.el.currentTime")
        check('cool-vibes' in M(gm)['src'] and t < 5 and M(gm)['playing'], 'Cool Vibes dips and starts over at its end')
        gm.click('[data-act=start]'); gm.wait_for_timeout(2500)
        check('spy-glass' in M(gm)['src'], 'loop 2 opens on Spy Glass')
        # Between songs: jump to 6 s before Spy Glass ends; it should dip out, then Fast Talkin fades in.
        gm.evaluate("() => { const e = window.__music.el; e.currentTime = e.duration - 6; }")
        gm.wait_for_timeout(3500)
        m = M(gm); print('  mid-dip:', m)
        check('spy-glass' in m['src'] and m['fade'] < 0.8, 'song fades out over its last seconds')
        gm.wait_for_timeout(4000)
        m = M(gm); print('  after dip:', m)
        check('fast-talkin' in m['src'] and m['playing'], 'next song in the rotation fades in')

        tool(pl, '#btn-sound'); pl.wait_for_timeout(200); pl.click('#snd-take'); pl.wait_for_timeout(2500)
        mp, mg = M(pl), M(gm); print('  after handoff pl:', mp, 'gm:', mg)
        check(mp['on'] and mp['mode'] == 'loop' and 'spy-glass' in mp['src'], 'player takes over the music, on the current loop track')
        check(not mg['on'], 'GM device goes quiet')
        check(pl.is_checked('#snd-chimes'), 'chimes follow the music device by default')
        pl.screenshot(path='/tmp/snd_player_dj.png')
        b.close()
finally:
    srv.terminate()
print('failures:', bad)
