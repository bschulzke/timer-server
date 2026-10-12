# Luck Dice counter in two real browsers. Run: python3 e2e_luck.py
import subprocess, time, os, re
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PORT='3919', DATA_FILE='/tmp/shenan-luck.json')
try: os.remove(env['DATA_FILE'])
except OSError: pass
srv = subprocess.Popen(['node', 'server.mjs'], env=env, cwd=HERE); time.sleep(1)
URL = 'http://localhost:3919/'
bad = 0
def check(c, name):
    global bad
    print(('pass ' if c else 'FAIL ') + name); bad += 0 if c else 1
def tool(pg, sel):
    if pg.is_visible('#btn-menu'): pg.click('#btn-menu'); pg.wait_for_timeout(150)
    pg.click(sel)
count = lambda pg: int(pg.inner_text('#luck .luck-head b'))
lit = lambda pg: len(pg.query_selector_all('#luck .die:not(.off)'))
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        dev = p.devices['iPhone 13']
        gm = b.new_context(**dev).new_page(); pl = b.new_context(**dev).new_page()
        for n, pg in (('gm', gm), ('pl', pl)): pg.on('pageerror', lambda e, n=n: print(n, 'page error', e))
        gm.goto(URL + '?test'); gm.wait_for_selector('[data-land=host]:not([disabled])')
        gm.click('[data-land=host]'); gm.wait_for_timeout(1500)
        tool(gm, '#btn-share'); gm.wait_for_timeout(300)
        code = re.search(r'#([A-Z0-9]{4})', gm.inner_text('#panel-share')).group(1)
        check(not gm.is_visible('#luck'), 'counter is off by default')
        check(not gm.is_checked('#luck-on'), 'GM sees the switch, unticked')
        gm.check('#luck-on'); gm.wait_for_timeout(300)
        gm.click('#panel-share .panel-x')

        pl.goto(URL + '#' + code); pl.wait_for_timeout(1500)
        check(pl.is_visible('#luck') and count(pl) == 20 and lit(pl) == 20, 'player sees 20 Luck Dice')
        box = pl.query_selector('#luck').bounding_box(); log = pl.query_selector('#marks').bounding_box()
        check(box['y'] < log['y'], 'dice sit above the timestamps on a phone')
        tool(pl, '#btn-share'); pl.wait_for_timeout(200)
        check(pl.query_selector('#luck-on') is None, 'players get no counter switch')
        pl.click('#panel-share .panel-x')

        check(pl.query_selector('#luck button.die, #luck [data-die]') is None, 'the dice are just a picture, not buttons')
        check(pl.is_disabled('[data-luck=add]') and not pl.is_disabled('[data-luck=spend]'), 'at 20, + is off and − is on')
        for _ in range(3): pl.click('[data-luck=spend]')
        check(count(pl) == 17 and lit(pl) == 17, 'three taps on − spend 3 right away, no confirm')
        pl.wait_for_timeout(500)
        check(count(gm) == 17 and count(pl) == 17, 'GM sees 17 too')
        pl.click('[data-luck=add]'); pl.wait_for_timeout(500)
        check(count(pl) == 18 and count(gm) == 18, 'a player can tap + to put one back')
        # Both tap fast at the same moment: every tap should count.
        for _ in range(4): pl.click('[data-luck=spend]'); gm.click('[data-luck=spend]')
        pl.wait_for_timeout(800)
        check(count(pl) == 10 and count(gm) == 10, 'fast taps from two players all add up (18 - 8 = 10)')
        for _ in range(9): gm.click('[data-luck=add]')
        gm.wait_for_timeout(600)
        check(count(gm) == 19 and count(pl) == 19, 'GM puts 9 back: both see 19')

        gm.click('[data-act=start]'); gm.wait_for_timeout(400)
        gm.click('[data-act=pause]'); gm.wait_for_timeout(400)
        check(count(pl) == 19, 'clock changes keep the count')
        pl.reload(); pl.wait_for_timeout(1500)
        check(count(pl) == 19, 'count survives a reload')

        gm.click('[data-act=start]'); gm.wait_for_timeout(300)
        gm.click('[data-act=skip]'); gm.click('[data-act=skip-yes]'); gm.wait_for_timeout(600)
        check(count(gm) == 20 and count(pl) == 20, 'a new loop resets to 20')

        for i in range(5): pl.click('[data-luck=spend]')
        pl.wait_for_timeout(400)
        gm.click('#btn-menu'); gm.click('#menu-new'); gm.wait_for_timeout(200); gm.click('[data-act=new-yes]'); gm.wait_for_timeout(600)
        check(count(pl) == 20 and pl.is_visible('#luck'), 'New game resets to 20 and keeps the counter on')

        tool(gm, '#btn-share'); gm.wait_for_timeout(200); gm.uncheck('#luck-on'); gm.wait_for_timeout(500)
        check(not pl.is_visible('#luck') and not gm.is_visible('#luck'), 'turning it off hides it for everyone')
        gm.click('#panel-share .panel-x')

        def rehost():
            gm.click('#btn-menu'); gm.click('#menu-leave'); gm.wait_for_timeout(200); gm.click('[data-act=leave-yes]'); gm.wait_for_timeout(400)
            gm.click('[data-land=host]'); gm.wait_for_timeout(1500)
            tool(gm, '#btn-share'); gm.wait_for_timeout(200)
            on = gm.is_checked('#luck-on'); gm.click('#panel-share .panel-x'); return on
        check(not rehost(), 'left with the counter off: the next hosted game starts with it off')
        tool(gm, '#btn-share'); gm.wait_for_timeout(200); gm.check('#luck-on'); gm.wait_for_timeout(300); gm.click('#panel-share .panel-x')
        check(rehost() and gm.is_visible('#luck') and count(gm) == 20, 'left with it on: the next hosted game starts with it on, at 20')

        solo = b.new_context(**dev).new_page()
        solo.goto(URL); solo.wait_for_selector('[data-land=solo]'); solo.click('[data-land=solo]'); solo.wait_for_timeout(400)
        tool(solo, '#btn-share'); solo.wait_for_timeout(200); solo.check('#luck-on'); solo.click('#panel-share .panel-x')
        solo.click('[data-luck=spend]'); solo.wait_for_timeout(200)
        solo.reload(); solo.wait_for_timeout(800)
        check(count(solo) == 19, 'solo game: spending works and is saved on the device')
        for _ in range(19): solo.click('[data-luck=spend]')
        check(count(solo) == 0 and solo.is_disabled('[data-luck=spend]'), 'at 0, − is off')
        for _ in range(3): solo.click('[data-luck=add]')
        solo.screenshot(path='/tmp/luck_phone.png')
        b.close()
finally:
    srv.terminate()
print('all passed' if not bad else '%d failed' % bad)
raise SystemExit(1 if bad else 0)
