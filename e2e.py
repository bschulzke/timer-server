# Two real browsers against a local server. Run: python3 e2e.py   (needs playwright + chromium)
import subprocess, time, os, re
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PORT='3912', DATA_FILE='/tmp/shenan-e2e.json', GRACE_MS='1500')
try: os.remove(env['DATA_FILE'])
except OSError: pass
srv = subprocess.Popen(['node','server.mjs'], env=env, cwd=HERE)
time.sleep(1)
URL='http://localhost:3912/'
bad = 0
def tool(pg, sel):
    # Phones keep the tool buttons in the three-dot menu.
    if pg.is_visible('#btn-menu'): pg.click('#btn-menu'); pg.wait_for_timeout(150)
    pg.click(sel)
def check(c, name):
    global bad
    print(('pass ' if c else 'FAIL ') + name); bad += 0 if c else 1
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        gctx = b.new_context(viewport={'width':420,'height':820}); pctx = b.new_context(viewport={'width':420,'height':820})
        gm = gctx.new_page(); pl = pctx.new_page()
        for n,pg in (('gm',gm),('pl',pl)): pg.on('pageerror', lambda e,n=n: print(n,'page error',e))
        gm.goto(URL); gm.wait_for_selector('[data-land=host]:not([disabled])')
        gm.click('[data-land=host]'); gm.wait_for_selector('#chip:not([hidden])')
        tool(gm, '#btn-share'); gm.wait_for_timeout(300)
        code = re.search(r'#([A-Z0-9]{4})', gm.inner_text('#panel-share'))
        check(bool(code), 'GM gets a join code'); code = code.group(1)
        link = gm.inner_text('#share-link'); check(link.startswith('http://localhost:3912/#'), 'join link points at our own server: ' + link)
        gm.keyboard.press('Escape')

        pl.goto(URL); pl.wait_for_selector('#join-code'); pl.fill('#join-code', code); pl.click('#join button[type=submit]')
        pl.wait_for_selector('#chip:not([hidden])', timeout=5000); pl.wait_for_timeout(500)
        check('Start loop' not in pl.inner_text('body') or pl.query_selector('[data-act=start]') is None, 'player has no Start button')
        check(gm.query_selector('[data-act=start]') is not None, 'GM has Start button')

        gm.click('[data-act=start]'); pl.wait_for_timeout(700)
        check(pl.query_selector('[data-act=mark]') is not None, 'player sees the running clock (Mark button appears)')
        t1 = pl.inner_text('#clock') if pl.query_selector('#clock') else ''
        # player adds a timestamp
        pl.click('[data-act=mark]'); pl.wait_for_timeout(300)
        pl.fill('#mk-note','Guard swapped'); pl.click('#mk-form button[type=submit]')
        pl.wait_for_timeout(1500)
        check('Guard swapped' in gm.inner_text('body'), 'GM sees the player\'s timestamp')

        # GM leaves the page: after the page's 30 s wait, the player is offered the takeover
        gm.goto('about:blank'); pl.wait_for_timeout(33000)
        check(pl.query_selector('[data-act=take]') is not None, 'player is offered the takeover')
        pl.click('[data-act=take]'); pl.wait_for_timeout(600)
        pl.click('[data-act=pause]'); pl.wait_for_timeout(600)
        check('resume' in pl.inner_text('body').lower(), 'player now runs the clock (paused it, Resume shown)')

        # server restart: the client reconnects on its own and the game survives
        srv.terminate(); srv.wait(); time.sleep(0.5)
        srv = subprocess.Popen(['node','server.mjs'], env=env, cwd=HERE); time.sleep(5)
        pl.wait_for_timeout(1500)
        check('resume' in pl.inner_text('body').lower() and 'guard swapped' in pl.inner_text('body').lower(), 'game and timestamp survive a server restart; client reconnects')
        pl.click('[data-act=start]'); pl.wait_for_timeout(600)
        check(pl.query_selector('[data-act=pause]') is not None and 'resume' not in pl.inner_text('body').lower(), 'control still works after reconnect')
        pl.screenshot(path='/tmp/e2e_player.png')
        b.close()
finally:
    srv.terminate()
print('failures:', bad)
