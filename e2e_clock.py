# Typing clock readings, microwave style, on a phone. Run: python3 e2e_clock.py
import subprocess, time, os
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PORT='3918', DATA_FILE='/tmp/shenan-clock.json')
srv = subprocess.Popen(['node', 'server.mjs'], env=env, cwd=HERE); time.sleep(1)
bad = 0
def check(c, name):
    global bad
    print(('pass ' if c else 'FAIL ') + name); bad += 0 if c else 1
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(**p.devices['iPhone 13']).new_page()
        pg.on('pageerror', lambda e: print('page error', e))
        pg.goto('http://localhost:3918/'); pg.wait_for_selector('[data-land=solo]')
        pg.click('[data-land=solo]'); pg.wait_for_timeout(500)
        val = lambda: pg.input_value('#mk-t')
        def fresh():
            pg.click('#btn-add'); pg.wait_for_timeout(150)
        def save():
            pg.click('#mk-form [type=submit]'); pg.wait_for_timeout(200)

        fresh()
        check(pg.get_attribute('#mk-t', 'inputmode') == 'numeric', 'number pad keyboard')
        pg.keyboard.type('3'); check(val() == '00:03', 'typing 3 shows 00:03')
        pg.keyboard.type('15'); check(val() == '03:15', 'then 15 shows 03:15')
        pg.keyboard.press('Backspace'); check(val() == '00:31', 'backspace takes the last digit off')
        pg.keyboard.type('5678'); check(val() == '31:56', 'a fifth digit is ignored')
        pg.keyboard.press('Backspace'); pg.keyboard.press('Backspace'); pg.keyboard.press('Backspace'); pg.keyboard.press('Backspace')
        check(val() == '', 'backspacing everything empties the field')
        pg.keyboard.type('0'); check(val() == '00:00', 'a typed 0 shows 00:00')
        pg.keyboard.type('5'); check(val() == '00:05', 'leading zeros are kept while typing')
        pg.keyboard.press('Backspace'); pg.keyboard.press('Backspace')
        pg.keyboard.type('1:30'); check(val() == '01:30', 'a typed colon is ignored')
        pg.keyboard.press('Backspace'); pg.keyboard.press('Backspace'); pg.keyboard.press('Backspace')
        pg.keyboard.type('175'); save()
        check(pg.inner_text('#marks .mark-t') == '02:15', '01:75 saves as 02:15')

        pg.click('#marks [data-edit]'); pg.wait_for_timeout(150)
        pg.click('#mk-t'); pg.wait_for_timeout(100)
        check(val() == '02:15', 'editing shows the saved time')
        pg.keyboard.type('9'); check(val() == '00:09', 'first digit on an existing time starts fresh')
        pg.keyboard.type('001'); check(val() == '90:01', 'four digits fill the field')
        save(); check(pg.is_visible('#mk-err') and '60:00' in pg.inner_text('#mk-err'), 'over 60:00 is refused with a clear message')
        pg.keyboard.press('Backspace'); check(not pg.is_visible('#mk-err'), 'the message clears when you edit')
        pg.fill('#mk-t', '14:00'); check(val() == '14:00', 'pasting a whole time works')
        save(); check(pg.inner_text('#marks .mark-t') == '14:00', 'edited time saves')

        fresh(); save()
        check(pg.is_visible('#mk-err'), 'an empty time is refused')
        b.close()
finally:
    srv.terminate()
print('all passed' if not bad else '%d failed' % bad)
raise SystemExit(1 if bad else 0)
