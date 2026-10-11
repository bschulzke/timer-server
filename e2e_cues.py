# Secret GM cues in two real browsers. Run: python3 e2e_cues.py
import subprocess, time, os, re
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PORT='3917', DATA_FILE='/tmp/shenan-cues.json')
try: os.remove(env['DATA_FILE'])
except OSError: pass
srv = subprocess.Popen(['node', 'server.mjs'], env=env, cwd=HERE); time.sleep(1)
URL = 'http://localhost:3917/'
NOTE = 'Rask leaves the bridge'
bad = 0
def tool(pg, sel):
    if pg.is_visible('#btn-menu'): pg.click('#btn-menu'); pg.wait_for_timeout(150)
    pg.click(sel)
def check(c, name):
    global bad
    print(('pass ' if c else 'FAIL ') + name); bad += 0 if c else 1
# Count every sound the page makes, to prove the heads-up is silent.
COUNT = "window.__osc = 0; const o = AudioContext.prototype.createOscillator; AudioContext.prototype.createOscillator = function(){ window.__osc++; return o.apply(this, arguments); };"
try:
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        dev = p.devices['iPhone 13']
        gctx = b.new_context(**dev); gctx.add_init_script(COUNT)
        gm = gctx.new_page(); pl = b.new_context(**dev).new_page()
        for n, pg in (('gm', gm), ('pl', pl)): pg.on('pageerror', lambda e, n=n: print(n, 'page error', e))
        sent = []
        gm.on('websocket', lambda ws: ws.on('framesent', lambda f: sent.append(f if isinstance(f, str) else str(f))))

        gm.goto(URL + '?test'); gm.wait_for_selector('[data-land=host]:not([disabled])')
        gm.click('[data-land=host]'); gm.wait_for_timeout(1500)
        gm.click('#btn-menu'); gm.wait_for_timeout(150)
        check(gm.inner_text('#btn-share').strip().upper() == 'GAME SETTINGS', 'phone menu calls the Game panel "Game settings"')
        gm.click('#btn-share'); gm.wait_for_timeout(300)
        code = re.search(r'#([A-Z0-9]{4})', gm.inner_text('#panel-share')).group(1)
        check(gm.query_selector('#cue-on') is not None and not gm.is_checked('#cue-on'), 'host sees the cue switch, off by default')
        check('players can see this screen' in gm.inner_text('#panel-share') and 'Shown on this device only' in gm.inner_text('#panel-share'), 'switch comes with the TV warning')
        gm.select_option('#speed', '10')
        gm.check('#cue-on'); gm.wait_for_timeout(200)
        gm.click('[data-share=cue-add]'); gm.wait_for_timeout(200)
        check(gm.is_visible('#mk-t') and not gm.is_visible('#mk-loop'), 'cue editor has a time but no loop')
        check(gm.inner_text('#mk-title').lower() == 'new secret cue', 'editor is titled as a secret cue')
        gm.fill('#mk-t', '59:30'); gm.fill('#mk-note', NOTE); gm.click('#mk-form [type=submit]'); gm.wait_for_timeout(300)
        rows = gm.query_selector_all('#marks .mark.cue')
        check(len(rows) == 1 and NOTE in rows[0].inner_text() and 'ONLY YOU' in rows[0].inner_text().upper(), 'cue shows in the host\'s list, marked only you')

        pl.goto(URL + '#' + code); pl.wait_for_timeout(1500)
        tool(pl, '#btn-share'); pl.wait_for_timeout(300)
        check(pl.query_selector('#cue-on') is None, 'player gets no cue switch')
        pl.click('#panel-share .panel-x')
        second = gctx.new_page(); second.goto(URL + '#' + code); second.wait_for_timeout(1500)
        check(second.query_selector('#marks .mark.cue') is None and second.query_selector('#cue-on') is None,
              'another tab in the host\'s own browser is a different device: no cues')
        second.close()

        gm.click('body', position={'x': 5, 'y': 300}); gm.wait_for_timeout(300)
        gm.click('[data-act=start]'); gm.wait_for_timeout(600)
        before = gm.evaluate('window.__osc')
        # 10x speed: 59:30 minus two minutes of lead is already due, so the heads-up is up right away
        gm.wait_for_function("() => document.getElementById('caption').classList.contains('cue')", timeout=5000)
        check(gm.inner_text('#cap-k').upper().startswith('COMING UP IN') and 'ONLY YOU' in gm.evaluate("() => getComputedStyle(document.getElementById('cap-k'), '::after').content").upper(),
              'heads-up is styled as a cue, with the only-you tag')
        check(NOTE in gm.inner_text('#cap-v'), 'heads-up names the cue')
        gm.wait_for_timeout(1500)
        check(gm.evaluate('window.__osc') == before, 'heads-up makes no sound')
        tool(gm, '#btn-sound'); gm.wait_for_timeout(200)
        gm.uncheck('#snd-chimes'); gm.check('#snd-chimes'); gm.wait_for_timeout(300)
        check(gm.evaluate('window.__osc') > before, '(control: a test chime on the same device is counted)')
        gm.click('#panel-sound .panel-x')
        pl.wait_for_timeout(500)
        txt = pl.inner_text('body')
        check(NOTE not in txt and pl.query_selector('#marks .mark.cue') is None, 'player sees no cue anywhere')
        check(not any(NOTE in f for f in sent), 'the cue never goes over the network')

        gm.reload(); gm.wait_for_timeout(2000)
        check(len(gm.query_selector_all('#marks .mark.cue')) == 1, 'cue survives a reload on the host device')
        gm.click('#marks [data-cue-edit]'); gm.wait_for_timeout(200)
        gm.click('#mk-del'); gm.wait_for_timeout(200)
        check(gm.query_selector('#marks .mark.cue') is None, 'cue can be deleted')
        gm.click('#btn-menu'); gm.click('#btn-share'); gm.wait_for_timeout(200)
        gm.click('[data-share=cue-add]'); gm.wait_for_timeout(200)
        gm.keyboard.type('4000'); gm.fill('#mk-note', NOTE); gm.click('#mk-form [type=submit]'); gm.wait_for_timeout(300)
        check(len(gm.query_selector_all('#marks .mark.cue')) == 1, 'cue added again')
        gm.click('#btn-menu'); gm.click('#menu-new'); gm.wait_for_timeout(200)
        gm.click('[data-act=new-yes]'); gm.wait_for_timeout(500)
        check(gm.query_selector('#marks .mark.cue') is None, 'New game clears the cues')
        gm.reload(); gm.wait_for_timeout(2000)
        check(gm.query_selector('#marks .mark.cue') is None, '...and they stay cleared after a reload')
        gm.click('#btn-menu'); gm.click('#btn-share'); gm.wait_for_timeout(200)
        check(gm.is_checked('#cue-on') and 'No cues yet' in gm.inner_text('#panel-share'), 'the switch stays on after New game')

        # Loading a scenario's cues
        count = lambda: len(gm.query_selector_all('#marks .mark.cue'))
        gm.click('[data-share=cue-scen]'); gm.wait_for_timeout(200)
        check(gm.is_visible('#panel-scen') and 'LOAD 3 CUES' in gm.inner_text('#scen-body').upper(), 'loader opens on the first scenario, with nothing to replace')
        gm.click('[data-scen="1"]'); gm.wait_for_timeout(100)
        check('Police arrive' in gm.inner_text('#scen-body') and 'LOAD 9 CUES' in gm.inner_text('#scen-body').upper(), 'picking Yacht-zee previews its 9 cues')
        gm.click('[data-scen-go=replace]'); gm.wait_for_timeout(300)
        check(count() == 9 and not gm.is_visible('#panel-scen'), 'Yacht-zee loads 9 cues into the list')
        check('02:35' in gm.inner_text('#marks'), 'loaded cue shows its clock reading')
        gm.click('#btn-menu'); gm.click('#btn-share'); gm.wait_for_timeout(200)
        gm.click('[data-share=cue-scen]'); gm.wait_for_timeout(200)
        gm.click('[data-scen="1"]'); gm.wait_for_timeout(100)
        check('REPLACE YOUR 9 CUES' in gm.inner_text('#scen-body').upper(), 'with cues already there, it offers Replace or Add')
        gm.click('[data-scen-go=add]'); gm.wait_for_timeout(300)
        check(count() == 9, 'adding the same scenario again adds no duplicates')
        gm.click('#btn-menu'); gm.click('#btn-share'); gm.wait_for_timeout(200)
        gm.click('[data-share=cue-scen]'); gm.wait_for_timeout(200)
        gm.click('[data-scen="0"]'); gm.click('[data-scen-go=add]'); gm.wait_for_timeout(300)
        check(count() == 12, 'adding Clowning Around keeps the Yacht-zee cues')
        gm.click('#btn-menu'); gm.click('#btn-share'); gm.wait_for_timeout(200)
        gm.click('[data-share=cue-scen]'); gm.wait_for_timeout(200)
        gm.click('[data-scen="2"]'); gm.click('[data-scen-go=replace]'); gm.wait_for_timeout(300)
        check(count() == 2, 'replacing with Around the World leaves its 2 cues')
        check(not any('Lund' in f for f in sent), 'loaded cues never go over the network')
        gm.click('#btn-menu'); gm.click('#btn-share'); gm.wait_for_timeout(200)
        gm.uncheck('#cue-on'); gm.wait_for_timeout(200)
        check('[data-share=cue-add]' and gm.query_selector('[data-share=cue-add]') is None, 'turning cues off hides the add button')
        gm.click('#panel-share .panel-x')
        gm.click('#btn-add'); gm.wait_for_timeout(200)
        check(gm.is_visible('#mk-loop') and gm.inner_text('#mk-note-k').upper() == 'WHAT HAPPENED', 'timestamp editor is back to normal')
        gm.screenshot(path='/tmp/cues_gm.png')
        b.close()
finally:
    srv.terminate()
print('all passed' if not bad else '%d failed' % bad)
raise SystemExit(1 if bad else 0)
