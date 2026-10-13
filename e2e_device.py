# Closing the GM's tab and coming back keeps you the GM. Run: python3 e2e_device.py
import subprocess, time, os, re
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PORT='3926', DATA_FILE='/tmp/shenan-device.json')
try: os.remove(env['DATA_FILE'])
except OSError: pass
srv = subprocess.Popen(['node', 'server.mjs'], env=env, cwd=HERE); time.sleep(1)
URL = 'http://localhost:3926/'
NOTE = 'Rask leaves the bridge'
bad = 0
def check(c, name):
    global bad
    print(('pass ' if c else 'FAIL ') + name); bad += 0 if c else 1
gm_controls = lambda pg: pg.is_visible('[data-act=start]')
has_cue = lambda pg: pg.query_selector('#marks .mark.cue') is not None
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(**p.devices['iPhone 13'])     # one browser on one phone: tabs share storage
        def tab(url=URL):
            pg = ctx.new_page(); pg.on('pageerror', lambda e: print('page error', e))
            pg.goto(url); pg.wait_for_timeout(1800); return pg
        a = tab(); a.click('[data-land=host]'); a.wait_for_timeout(1500)
        a.click('#btn-menu'); a.click('#btn-share'); a.wait_for_timeout(200)
        code = re.search(r'#([A-Z0-9]{4})', a.inner_text('#panel-share')).group(1)
        a.check('#cue-on'); a.click('[data-share=cue-add]'); a.wait_for_timeout(200)
        a.keyboard.type('4000'); a.fill('#mk-note', NOTE); a.click('#mk-form [type=submit]'); a.wait_for_timeout(300)
        check(gm_controls(a) and has_cue(a), 'tab 1 hosts, with a secret cue')
        a.close()

        b2 = tab()
        check(gm_controls(b2), 'close the tab and come back: still the GM')
        check(has_cue(b2), '...and the secret cue is back')
        c = tab()
        check(not gm_controls(c) and not has_cue(c), 'a second tab open at the same time is a player, with no cues')
        other = b.new_context(**p.devices['iPhone 13']).new_page(); other.goto(URL + '#' + code); other.wait_for_timeout(1500)
        ready = 'READY' in other.inner_text('#titleblock').upper()
        b2.click('[data-act=start]'); other.wait_for_timeout(800)
        check(ready and 'READY' not in other.inner_text('#titleblock').upper(), "the server takes the returning GM's clock commands")
        b2.close(); c.close()

        d = tab()
        check(gm_controls(d) or d.is_visible('[data-act=pause]'), 'close both, open one: the GM comes back, not the newer player tab')
        d.reload(); d.wait_for_timeout(1500)
        check(d.is_visible('[data-act=pause]') and has_cue(d), 'a reload keeps the GM too')
        b.close()
finally:
    srv.terminate()
print('all passed' if not bad else '%d failed' % bad)
raise SystemExit(1 if bad else 0)
