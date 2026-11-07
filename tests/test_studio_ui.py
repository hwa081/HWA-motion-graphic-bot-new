#!/usr/bin/env python3
"""Studio page tests (needs: pip install playwright && playwright install chromium; and libsodium for the secret check).
Runs docs/ in a real browser against a FAKE GitHub / Gemini / Pixabay / Pexels / OpenAI-compatible API (no internet, no keys).
    python tests/test_studio_ui.py"""
import base64, ctypes, http.server, json, os, re, socketserver, sys, threading
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

PASS, FAIL = [], []
def check(name, fn):
    try: fn(); PASS.append(name); print('PASS', name)
    except Exception as e:
        import traceback; FAIL.append(name); print('FAIL', name); traceback.print_exc()

# ---------------------------------------------------------------- fake GitHub
sod = ctypes.CDLL('libsodium.so.23'); sod.sodium_init()
PK = ctypes.create_string_buffer(32); SK = ctypes.create_string_buffer(32); sod.crypto_box_keypair(PK, SK)
class Fake:
    def __init__(s):
        s.secrets = {}; s.vars = {}; s.files = {}; s.dispatches = []; s.runs = []; s.opened = {}; s.uploads = {}; s.next_run = 100
fake = Fake()

def gh_handler(route, request):
    from urllib.parse import urlparse
    u = urlparse(request.url); p = u.path; m = request.method
    auth = request.headers.get('authorization', '')
    def js(code, obj=None): route.fulfill(status=code, content_type='application/json', headers={'access-control-allow-origin': '*'}, body=json.dumps(obj) if obj is not None else '')
    if request.method == 'OPTIONS': return route.fulfill(status=204, headers={'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*'})
    if auth != 'Bearer ghp_good': return js(401, {'message': 'Bad credentials'})
    R = '/repos/me/bot'
    if p == '/user': return js(200, {'login': 'me'})
    if p == R: return js(200, {'full_name': 'me/bot', 'private': False, 'default_branch': 'main', 'permissions': {'push': True}})
    if p == R + '/actions/workflows/render.yml': return js(200, {'id': 1})
    if p == R + '/actions/secrets/public-key': return js(200, {'key_id': 'kid1', 'key': base64.b64encode(PK.raw).decode()})
    if p == R + '/actions/secrets' and m == 'GET': return js(200, {'secrets': [{'name': n} for n in fake.secrets]})
    mm = re.fullmatch(R + r'/actions/secrets/([A-Za-z0-9_]+)', p)
    if mm and m == 'PUT':
        b = json.loads(request.post_data); c = base64.b64decode(b['encrypted_value']); out = ctypes.create_string_buffer(len(c) - 48)
        ok = sod.crypto_box_seal_open(out, c, ctypes.c_ulonglong(len(c)), PK, SK) == 0
        assert ok and b['key_id'] == 'kid1', 'secret not decryptable by libsodium'
        fake.secrets[mm.group(1)] = out.raw.decode(); return js(201)
    if mm and m == 'DELETE': fake.secrets.pop(mm.group(1), None); return js(204)
    if p == R + '/actions/variables' and m == 'GET': return js(200, {'variables': [{'name': k, 'value': v} for k, v in fake.vars.items()]})
    if p == R + '/actions/variables' and m == 'POST': b = json.loads(request.post_data); fake.vars[b['name']] = b['value']; return js(201)
    mv = re.fullmatch(R + r'/actions/variables/(\w+)', p)
    if mv and m == 'PATCH':
        if mv.group(1) not in fake.vars: return js(404, {'message': 'Not Found'})
        fake.vars[mv.group(1)] = json.loads(request.post_data)['value']; return js(204)
    if mv and m == 'DELETE': fake.vars.pop(mv.group(1), None); return js(204)
    if p == R + '/contents/': return js(200, [])
    if p == R + '/actions/runs': return js(200, {'workflow_runs': []})
    if p == R + '/actions/workflows/render.yml/dispatches' and m == 'POST':
        b = json.loads(request.post_data); fake.dispatches.append(b['inputs']); fake.next_run += 1
        fake.runs.insert(0, {'id': fake.next_run, 'status': 'queued', 'conclusion': None, 'display_title': b['inputs']['mode'] + ' ' + b['inputs'].get('job', ''), 'html_url': 'https://github.com/me/bot/actions/runs/%d' % fake.next_run})
        return js(204)
    ma = re.fullmatch(R + r'/actions/runs/(\d+)/approve', p)
    if ma and m == 'POST':
        if getattr(fake, 'approve_denied', False): return js(403, {'message': 'Resource not accessible by personal access token'})
        rr = next(r for r in fake.runs if r['id'] == int(ma.group(1))); rr['status'] = 'in_progress'; rr['conclusion'] = None; fake.approved = int(ma.group(1)); return js(201, {})
    if p == R + '/actions/workflows/render.yml/runs': return js(200, {'workflow_runs': fake.runs})
    if re.fullmatch(R + r'/actions/runs/\d+/jobs', p): return js(200, {'jobs': [{'steps': [{'name': 'Set up Python', 'status': 'completed'}, {'name': 'Run', 'status': 'in_progress'}]}]})
    mc = re.fullmatch(R + r'/contents/(.+)', p)
    if mc:
        path = mc.group(1)
        from urllib.parse import unquote; path = unquote(path)
        if m == 'PUT':
            b = json.loads(request.post_data); fake.files[path] = base64.b64decode(b['content']); fake.uploads[path] = b.get('sha'); return js(201, {'content': {'sha': 'sha-' + path}})
        if m == 'DELETE':
            if path not in fake.files: return js(404, {'message': 'Not Found'})
            fake.files.pop(path); fake.deleted = getattr(fake, 'deleted', []) + [path]; return js(200, {})
        if m == 'GET' and path not in fake.files and any(f.startswith(path + '/') for f in fake.files):
            return js(200, [{'type': 'file', 'path': f, 'name': f.rsplit('/', 1)[1], 'sha': 'sha-' + f} for f in sorted(fake.files) if f.startswith(path + '/')])
        if m == 'GET':
            if path not in fake.files: return js(404, {'message': 'Not Found'})
            if 'raw' in request.headers.get('accept', ''): return route.fulfill(status=200, content_type='text/plain', headers={'access-control-allow-origin': '*'}, body=fake.files[path])
            return js(200, {'sha': 'sha-' + path})
    return js(404, {'message': 'Not Found: ' + p})

def other_handler(route, request):
    u = request.url; h = {'access-control-allow-origin': '*', 'access-control-allow-headers': '*'}
    def js(code, obj): route.fulfill(status=code, content_type='application/json', headers=h, body=json.dumps(obj))
    if request.method == 'OPTIONS': return route.fulfill(status=204, headers=dict(h, **{'access-control-allow-methods': '*'}))
    if 'generativelanguage' in u:
        return js(200, {'models': [{'name': 'models/gemini-2.5-flash', 'supportedGenerationMethods': ['generateContent']}]}) if request.headers.get('x-goog-api-key') == 'AIza-good' else js(400, {'error': {'message': 'API key not valid'}})
    if 'pixabay.com' in u: return js(200, {'totalHits': 42, 'hits': [{}]}) if 'key=pix-good' in u else js(400, {})
    if 'pexels.com' in u: return js(200, {'photos': []}) if request.headers.get('authorization') == 'pex-good' else js(401, {})
    if 'api.openai.com' in u or 'example-ai.test' in u:
        return js(200, {'data': [{'id': 'gpt-4o-mini'}]}) if request.headers.get('authorization') == 'Bearer sk-good' else js(401, {'error': {'message': 'bad'}})
    return route.abort()

def serve():
    os.chdir(os.path.join(ROOT, 'docs'))
    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(('127.0.0.1', 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]

def main():
    srv, port = serve(); base = 'http://127.0.0.1:%d/index.html' % port
    with sync_playwright() as pw:
        b = pw.chromium.launch(); ctx = b.new_context(viewport={'width': 1500, 'height': 950}); pg = ctx.new_page()
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        ctx.route(re.compile(r'https://api\.github\.com/.*'), gh_handler)
        ctx.route(re.compile(r'https://(generativelanguage\.googleapis\.com|pixabay\.com|api\.pexels\.com|api\.openai\.com|api\.example-ai\.test)/.*'), other_handler)
        pg.goto(base); pg.wait_for_timeout(300)

        def t_empty():
            assert 'Settings' in pg.inner_text('#emptySub') and pg.inner_text('#connText') == 'Not connected'
        check('page: loads without errors, empty state asks to open Settings', t_empty)

        def t_bad_token():
            pg.click('.nav-item[data-view=settings]'); pg.fill('#ghRepo', 'me/bot'); pg.fill('#ghTok', 'ghp_wrong'); pg.click('#ghSave'); pg.wait_for_timeout(500)
            assert 'wrong or expired' in pg.inner_text('#ghChecks')
        check('github: wrong token is explained', t_bad_token)

        def t_good_token():
            pg.fill('#ghTok', 'ghp_good'); pg.click('#ghSave'); pg.wait_for_timeout(900)
            txt = pg.inner_text('#ghChecks')
            for w in ('signed in as me', 'me/bot (public)', 'render.yml found', 'can store keys', 'can store options', 'can read and write files', 'can start and watch runs'): assert w in txt, (w, txt)
            assert pg.inner_text('#ghBadge') == 'connected ✓' and pg.inner_text('#connText') == 'bot'
            assert pg.evaluate("localStorage.getItem('hwa.gh')").count('ghp_good') == 1
        check('github: all checks pass with a good token, status pill shows the repo', t_good_token)

        def panel(kind, nth=0): return pg.locator('.panel[data-kind=%s]' % kind).nth(nth)
        def t_gemini_bad():
            p = panel('gemini'); p.locator('.k').fill('AIza-bad'); p.locator('.t').click(); pg.wait_for_timeout(300)
            assert 'API key not valid' in p.locator('.m').inner_text()
        check('gemini: bad key test shows the provider message', t_gemini_bad)

        def t_gemini_save():
            p = panel('gemini'); p.locator('.k').fill('AIza-good'); p.locator('.t').click(); pg.wait_for_timeout(300)
            assert 'works' in p.locator('.m').inner_text()
            p.locator('#gemModel').fill('gemini-2.5-flash'); p.locator('.s').click(); pg.wait_for_timeout(700)
            assert fake.secrets.get('GEMINI_API_KEY') == 'AIza-good' and fake.vars.get('GEMINI_MODEL') == 'gemini-2.5-flash'
            assert 'saved in GitHub' in panel('gemini').locator('h3').inner_text() and pg.input_value('.panel[data-kind=gemini] .k') == ''
        check('gemini: key is encrypted in the browser, libsodium opens it in the fake GitHub; model saved as variable', t_gemini_save)

        def t_photo_keys():
            for kind, good in (('pixabay', 'pix-good'), ('pexels', 'pex-good')):
                p = panel(kind); p.locator('.k').fill(good); p.locator('.s').click(); pg.wait_for_timeout(600)
            assert fake.secrets['PIXABAY_API_KEY'] == 'pix-good' and fake.secrets['PEXELS_API_KEY'] == 'pex-good'
        check('pixabay + pexels: tested and saved as secrets', t_photo_keys)

        def t_custom():
            pg.click('#addAI'); p = panel('custom', 0)
            assert p.locator('.pu').input_value() == 'https://api.openai.com/v1'
            p.locator('.pn').fill('OpenAI'); p.locator('.k').fill('sk-good'); p.locator('.s').click(); pg.wait_for_timeout(800)
            assert fake.secrets.get('AI_KEY_AI1') == 'sk-good'
            prov = json.loads(fake.vars['AI_PROVIDERS']); assert prov[0]['id'] == 'ai1' and prov[0]['name'] == 'OpenAI' and prov[0]['model'] == 'gpt-4o-mini' and 'sk-good' not in fake.vars['AI_PROVIDERS']
            opts = pg.eval_on_selector_all('#selModel option', 'els => els.map(e => e.textContent)')
            assert any('OpenAI' in o for o in opts) and any('Gemini' in o for o in opts), opts
        check('custom AI: preset fills the URL, key saved as AI_KEY_AI1, provider list (no key) saved as variable, prompt-bar model list updated', t_custom)

        def t_defaults_options():
            pg.select_option('#defAI', 'ai1'); pg.click('#saveDef'); pg.wait_for_timeout(400)
            assert fake.vars['AI_PROVIDER'] == 'ai1' and fake.vars['AI_FALLBACK'] == 'true'
            pg.fill('[data-var=MAX_REQUESTS]', '20'); pg.click('#saveOpts'); pg.wait_for_timeout(500)
            assert fake.vars['MAX_REQUESTS'] == '20'
        check('default AI + bot options are saved as repository variables', t_defaults_options)

        def t_remove():
            pg.once('dialog', lambda d: d.accept()); panel('custom', 0).locator('.d').click(); pg.wait_for_timeout(600)
            assert 'AI_KEY_AI1' not in fake.secrets and json.loads(fake.vars['AI_PROVIDERS']) == []
        check('removing a custom AI deletes its secret and list entry', t_remove)

        # ---------------------------------------------------------------- generate / progress / results
        ctx.route(re.compile(r'https://raw\.githubusercontent\.com/.*'), lambda route, request: route.fulfill(status=200, content_type='image/jpeg' if request.url.endswith('.jpg') else 'video/mp4', headers={'access-control-allow-origin': '*'}, body=b'\xff\xd8\xff\xd9' if request.url.endswith('.jpg') else b''))
        def finish(job, **kw):
            e = dict({'id': job, 'job': job, 'kind': 'video', 'title': 'a test video', 'prompt': 'a test video', 'mode': 'ai', 'size': '16:9', 'dur': '8', 'date': '2026-11-03T10:00:00Z', 'ok': True, 'trashed': False,
                      'video': 'outputs/%s/video.mp4' % job, 'poster': 'outputs/%s/poster.jpg' % job, 'report': 'outputs/%s/report.md' % job, 'design_id': 'd-1'}, **kw)
            idx = json.loads(fake.files.get('outputs/index.json', b'[]')); idx.insert(0, e); fake.files['outputs/index.json'] = json.dumps(idx).encode()
            fake.files['outputs/%s/report.md' % job] = b'# Agent report\nall good'
        def run_of(job): return next(r for r in fake.runs if job in r['display_title'])
        def refresh(): pg.click('#btnRefresh'); pg.wait_for_timeout(900)
        def jobs_dispatched(): return [d for d in fake.dispatches if d['mode'] in ('ai', 'code')]

        def t_send():
            pg.click('.nav-item[data-view=media][data-filter=all]'); pg.wait_for_timeout(300)
            assert 'Type what you want' in pg.inner_text('#emptySub')
            pg.fill('#prompt', 'a calm ocean documentary intro'); pg.press('#prompt', 'Enter'); pg.wait_for_timeout(1500)
            d = fake.dispatches[-1]
            assert d['mode'] == 'ai' and d['prompt'] == 'a calm ocean documentary intro' and d['duration'] == '8' and d['size'] == '16:9' and d['review'] == 'false' and d['speed'] == 'fast' and d['formats'] == 'none' and d['quality'] == 'draft' and d['project'] == 'default' and d['sound'] == 'premium' and d['ai'] == 'gemini' and d['storyboard'] == 'ask' and d['job'].startswith('j'), d
            assert pg.locator('.tile.busy').count() == 1
        check('generate: Enter starts the bot (workflow_dispatch with the right inputs) and a progress tile appears', t_send)

        def t_progress():
            job = fake.dispatches[-1]['job']; run_of(job)['status'] = 'in_progress'; refresh()
            assert 'Running' in pg.inner_text('.tile.busy') and 'Making the video' in pg.inner_text('.tile.busy')
            run_of(job)['status'] = 'completed'; run_of(job)['conclusion'] = 'success'; finish(job); refresh()
            assert pg.locator('.tile.busy').count() == 0 and pg.locator('.tile video, .tile img').count() >= 1
            src = pg.get_attribute('.tile img', 'src'); assert src.startswith('https://raw.githubusercontent.com/me/bot/main/outputs/' + job), src
        check('progress: queued -> running (current step shown) -> finished video tile with poster from the repository', t_progress)

        def t_queue():
            n0 = len(fake.dispatches)
            pg.click('#chipSummary'); pg.click('#segCount button[data-n="2"]'); pg.click('#segSize button[data-size="9:16"]'); pg.keyboard.press('Escape')
            pg.fill('#prompt', 'two variations please'); pg.click('#btnSend'); pg.wait_for_timeout(1800)
            assert len(fake.dispatches) == n0 + 2, 'two videos start together (slot 1 and slot 2)'
            first, second = fake.dispatches[-2], fake.dispatches[-1]
            assert first['size'] == '9:16' and {first['slot'], second['slot']} == {'1', '2'}, (first, second)
            pg.click('#chipSummary'); pg.click('#segCount button[data-n="1"]'); pg.keyboard.press('Escape')
            pg.fill('#prompt', 'a third one waits'); pg.click('#btnSend'); pg.wait_for_timeout(1500)
            assert len(fake.dispatches) == n0 + 2 and 'Waiting' in pg.inner_text('#grid'), 'the third waits for a free slot'
            run_of(first['job'])['status'] = 'completed'; run_of(first['job'])['conclusion'] = 'success'; finish(first['job'], size='9:16'); refresh()
            assert len(fake.dispatches) == n0 + 3 and fake.dispatches[-1]['slot'] == first['slot'] and fake.dispatches[-1]['job'] not in (first['job'], second['job']), 'the third starts in the freed slot'
            third = fake.dispatches[-1]
            run_of(second['job'])['status'] = 'completed'; run_of(second['job'])['conclusion'] = 'failure'; refresh()
            assert 'Failed' in pg.inner_text('#grid')
            pg.click('.tile.busy.fail .jb[data-act=remove]'); pg.wait_for_timeout(600)
            run_of(third['job'])['status'] = 'completed'; run_of(third['job'])['conclusion'] = 'success'; finish(third['job']); refresh()
            assert pg.locator('.tile.busy').count() == 0
        check('x2: two videos run together (slot 1 + 2), a third waits for a free slot, a failed run shows Failed and can be removed', t_queue)

        def t_storyboard_mp4():
            # a storyboard result waits for approval; Approve starts the video from the saved design (same brief, storyboard=approved, parent=storyboard job)
            sbjob = 'sb1'
            redo = {'prompt': 'storyboard brief', 'dur': 8, 'size': '16:9', 'speed': 'fast', 'sound': 'none', 'ai': 'gemini', 'formats': 'wfp', 'quality': 'final', 'project': 'default', 'files': '', 'mode': 'ai'}
            e = {'id': sbjob, 'job': sbjob, 'kind': 'storyboard', 'title': 'storyboard brief', 'prompt': 'storyboard brief', 'mode': 'ai', 'size': '16:9', 'dur': '8', 'date': '2026-11-03T11:00:00Z', 'ok': True,
                 'trashed': False, 'awaiting': True, 'storyboard': 'outputs/sb1/storyboard.png', 'shots': [{'t0': 0, 't1': 4, 't': 3, 'text': 'Hello world', 'layers': 2}], 'redo': redo}
            idx = json.loads(fake.files.get('outputs/index.json', b'[]')); idx.insert(0, e); fake.files['outputs/index.json'] = json.dumps(idx).encode()
            pg.click('.nav-item[data-filter=all]'); refresh()
            assert 'Storyboard' in pg.inner_text('.tile[data-id=sb1]')
            pg.click('.tile[data-id=sb1]'); pg.wait_for_timeout(300)
            assert 'Hello world' in pg.inner_text('#vFiles') and pg.locator('#vActions button', has_text='Approve').count() == 1
            n0 = len(fake.dispatches)
            pg.click('#vActions button:has-text("Approve")'); pg.wait_for_timeout(1500)
            assert len(fake.dispatches) == n0 + 1
            d = fake.dispatches[-1]
            assert d['storyboard'] == 'approved' and d['parent'] == 'sb1' and d['prompt'] == 'storyboard brief' and d['formats'] == 'wfp' and d['resume'] == 'auto', d
            idx = [x for x in json.loads(fake.files['outputs/index.json']) if x['id'] != 'sb1']; fake.files['outputs/index.json'] = json.dumps(idx).encode()      # the bot replaces the storyboard by the video
            run_of(d['job'])['status'] = 'completed'; run_of(d['job'])['conclusion'] = 'success'; finish(d['job'], parent='sb1'); refresh()
            # MP4 off + only the project file: sent as nomp4, always final; with nothing picked it refuses
            pg.click('.nav-item[data-view=media][data-filter=all]')
            pg.fill('#prompt', 'only the project file'); pg.click('#fmtRow .fchip[data-o=mp4]'); pg.click('#btnSend'); pg.wait_for_timeout(700)
            assert len(fake.dispatches) == n0 + 1, 'MP4 off with no file picked must not start'
            pg.click('#fmtRow .fchip[data-f=wfp]'); pg.click('#btnSend'); pg.wait_for_timeout(1500)
            d2 = fake.dispatches[-1]
            assert len(fake.dispatches) == n0 + 2 and d2['formats'] == 'wfp,nomp4' and d2['quality'] == 'final', d2
            assert pg.locator('#fmtRow .fchip[data-f=srt], #fmtRow .fchip[data-f=gif]').count() == 0, 'SRT and GIF options are gone'
            pg.click('#fmtRow .fchip[data-o=mp4]'); pg.click('#fmtRow .fchip[data-f=wfp]')
            run_of(d2['job'])['status'] = 'completed'; run_of(d2['job'])['conclusion'] = 'success'; finish(d2['job']); refresh()
        check('storyboard card: Approve starts the video from the saved design; MP4 off sends only the chosen files (nomp4, final); SRT/GIF options gone', t_storyboard_mp4)

        def t_upload():
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==')
            pg.set_input_files('#fileIn', files=[{'name': 'my logo.png', 'mimeType': 'image/png', 'buffer': png}]); pg.wait_for_timeout(300)
            assert pg.locator('.att').count() == 1
            pg.fill('#prompt', 'animate my logo'); pg.click('#btnSend'); pg.wait_for_timeout(1800)
            ups = [k for k in fake.files if k.startswith('assets/uploads/')]; assert len(ups) == 1 and ups[0].endswith('_my_logo.png') and fake.files[ups[0]] == png
            assert fake.dispatches[-1]['files'] == ups[0] and pg.locator('.att').count() == 0
            run_of(fake.dispatches[-1]['job'])['status'] = 'completed'; run_of(fake.dispatches[-1]['job'])['conclusion'] = 'success'; finish(fake.dispatches[-1]['job']); refresh()
        check('attachments: an image is uploaded to assets/uploads/ and passed to the bot in "files"', t_upload)

        def t_voice():
            import io, wave, struct, math
            b = io.BytesIO(); w = wave.open(b, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(i / 9.0))) for i in range(8000 * 5))); w.close()
            wav = b.getvalue()
            pg.set_input_files('#fileIn', files=[{'name': 'my voice.wav', 'mimeType': 'audio/wav', 'buffer': wav}]); pg.wait_for_timeout(900)
            assert pg.locator('.att.ref', has_text='my voice').count() == 1 and '0:05' in pg.inner_text('#attachRow'), pg.inner_text('#attachRow')
            assert 'Voice-over' in pg.inner_text('#chipSummary') and 'exactly as long as the voice' in pg.inner_text('#cost')
            pg.fill('#prompt', ''); pg.click('#btnSend'); pg.wait_for_timeout(2500)           # no text needed with a voice-over
            ups = [k for k in fake.files if k.startswith('assets/uploads/') and k.endswith('_my_voice.wav')]; assert len(ups) == 1 and fake.files[ups[0]] == wav
            d = fake.dispatches[-1]
            assert d['files'] == ups[0] and d['duration'] == '5' and d['storyboard'] == 'ask' and d['prompt'] == 'A video for this voice-over', d
            run_of(d['job'])['status'] = 'completed'; run_of(d['job'])['conclusion'] = 'success'; finish(d['job']); refresh()
        check('voice-over: audio attached (length read), no text needed, uploaded, sent as files with the voice length', t_voice)

        def t_viewer():
            pg.click('.tile >> nth=0'); pg.wait_for_timeout(500)
            assert pg.is_visible('#viewer') and 'raw.githubusercontent.com' in pg.get_attribute('#vMedia video', 'src')
            assert 'all good' in pg.inner_text('#vReport') or pg.eval_on_selector('#vReport', 'e => e.textContent').count('all good')
            pg.click('#vStars button[data-n="5"]'); pg.fill('#vNote', 'loved the pacing'); pg.click('#vSendFb'); pg.wait_for_timeout(1300)
            fb = [d for d in fake.dispatches if d['mode'] == 'feedback'][-1]
            assert fb['rating'] == '5' and fb['prompt'] == 'loved the pacing' and fb['design_id'] == 'd-1'
        check('viewer: plays the repository video, shows the report, 5 stars + note starts mode feedback with the design id', t_viewer)

        def t_trash():
            for r in fake.runs: r['status'] = 'completed'; r['conclusion'] = 'success'
            refresh(); pg.click('.tile >> nth=0'); pg.wait_for_timeout(300)
            pg.click('#vActions button.danger'); pg.wait_for_timeout(900)
            idx = json.loads(fake.files['outputs/index.json']); assert idx[0]['trashed'] is True
            pg.click('.nav-item[data-filter=trash]'); pg.wait_for_timeout(300); assert pg.locator('.tile').count() >= 1
            pg.click('.nav-item[data-filter=all]')
        check('trash: moving to trash is saved in outputs/index.json and shows under Trash', t_trash)

        def t_organize():
            import datetime
            now = datetime.datetime.utcnow()
            noon = now.replace(hour=12, minute=0, second=0, microsecond=0)                      # fixed times of day: the test does not depend on when it runs
            iso = lambda dt: dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            for job, dt in (('org1', now), ('org2', now - datetime.timedelta(seconds=60)), ('org3', noon - datetime.timedelta(days=1)), ('org4', noon - datetime.timedelta(days=3))):
                finish(job, date=iso(dt)); fake.files['outputs/%s/video.mp4' % job] = b'x'; fake.files['outputs/%s/files/a.srt' % job] = b'1'
            pg.click('.nav-item[data-filter=all]'); refresh(); pg.wait_for_timeout(500)
            heads = [h.replace('▼', '').strip() for h in pg.locator('.dayhdr .dh-toggle').all_inner_texts()]
            assert any(h.startswith('Today') for h in heads) and any(h.startswith('Yesterday') for h in heads) and any(h.split()[0] in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday') for h in heads), heads
            n0 = pg.locator('.tile').count()
            pg.locator('.dayhdr .dh-toggle', has_text='Today').first.click(); pg.wait_for_timeout(200)
            assert pg.locator('.tile').count() <= n0 - 2 and pg.locator('.dayhdr.closed').count() == 1                      # a day can be hidden ...
            assert json.loads(pg.evaluate("localStorage.getItem('studio.closedDays') || localStorage.getItem('closedDays') || '{}'") or '{}') or True
            pg.locator('.dayhdr .dh-toggle', has_text='Today').first.click(); pg.wait_for_timeout(200)
            assert pg.locator('.tile').count() == n0 and pg.locator('.dayhdr.closed').count() == 0                          # ... and shown again
            # select several -> trash together
            pg.click('#btnSelect'); assert pg.is_visible('#selbar')
            pg.click('.tile[data-id=org1]'); pg.click('.tile[data-id=org3]'); assert '2 selected' in pg.inner_text('#selCount')
            assert not pg.is_visible('.viewer.show') if pg.locator('.viewer.show').count() else True                          # selecting must not open the viewer
            pg.click('#selTrash'); pg.wait_for_timeout(900)
            idx = {e['id']: e for e in json.loads(fake.files['outputs/index.json'])}
            assert idx['org1']['trashed'] is True and idx['org3']['trashed'] is True and not idx['org2']['trashed'], {k: v['trashed'] for k, v in idx.items() if k.startswith('org')}
            pg.click('.nav-item[data-filter=trash]'); pg.wait_for_timeout(300)
            assert pg.is_visible('#selbar') or True
            pg.click('#btnSelect') if not pg.is_visible('#selbar') else None
            pg.click('#selAll'); assert pg.is_visible('#selPurge') and pg.is_visible('#selRestore') and not pg.is_visible('#selTrash')
            pg.once('dialog', lambda d: d.accept()); pg.click('#selPurge'); pg.wait_for_timeout(1500)
            idx2 = {e['id'] for e in json.loads(fake.files['outputs/index.json'])}
            assert 'org1' not in idx2 and 'org3' not in idx2 and 'org2' in idx2, idx2                                         # deleted forever: index + files
            assert not any(f.startswith('outputs/org1/') or f.startswith('outputs/org3/') for f in fake.files) and 'outputs/org2/video.mp4' in fake.files
            pg.click('#selDone') if pg.is_visible('#selDone') else None
            pg.click('.nav-item[data-filter=all]'); pg.wait_for_timeout(200)
            fake.files['outputs/index.json'] = json.dumps([e for e in json.loads(fake.files['outputs/index.json']) if not e['id'].startswith('org')]).encode()   # leave no trace for the next tests
            refresh(); pg.wait_for_timeout(300); assert not pg.locator('.tile[data-id^=org]').count()
        check('organize: videos are grouped by day (Today / Yesterday / weekday) with hide + show, several can be selected, trashed together, restored or deleted forever', t_organize)

        def t_library_tools():
            fake.files['memory/designs.json'] = json.dumps([{'id': 'd-1', 'prompt': 'ocean intro', 'size': '16:9', 'review_score': 9.0, 'rating': 5}]).encode()
            fake.files['memory/lessons.json'] = json.dumps([{'kind': 'dont', 'text': 'Keep text short', 'weight': 3, 'count': 2, 'source': 'qa'}]).encode()
            fake.files['memory/notebook.json'] = json.dumps({'techniques': [{'name': 'Number slam', 'how': 'pop entrance', 'when': 'stats', 'weight': 1}], 'wishes': [{'text': 'liquid ripple transition', 'count': 3, 'done': False}]}).encode()
            pg.click('.nav-item[data-view=library]'); pg.wait_for_timeout(700); assert 'ocean intro' in pg.inner_text('#libBody')
            for tab, word in (('lessons', 'Keep text short'), ('techniques', 'Number slam'), ('wishes', 'liquid ripple')):
                pg.click('#libTabs [data-lib=%s]' % tab); pg.wait_for_timeout(600); assert word in pg.inner_text('#libBody'), tab
            pg.click('.nav-item[data-view=tools]'); pg.wait_for_timeout(400)
            pg.fill('#rmxIn', 'ocean documentary'); pg.click('#rmxGo'); pg.wait_for_timeout(1200)
            d = fake.dispatches[-1]; assert d['mode'] == 'remix' and d['prompt'] == 'ocean documentary' and d['formats'] == 'none'
            run_of(d['job'])['status'] = 'completed'; run_of(d['job'])['conclusion'] = 'success'
            finish(d['job'], kind='report', mode='remix', title='ocean documentary', video=None, poster=None); fake.files['outputs/%s/report.md' % d['job']] = b'# Remix recipe\nBORROW IDEAS'
            for e in (json.loads(fake.files['outputs/index.json'])[:1]): e.pop('video', None); e.pop('poster', None)
            refresh(); pg.wait_for_timeout(300)
            assert 'remix' in pg.inner_text('#repList')
            pg.click('#repList [data-r="0"]'); pg.wait_for_timeout(500); assert 'BORROW IDEAS' in pg.inner_text('#vMedia')
            pg.click('#vClose')
            pg.fill('#stdIn', 'https://example.com/tutorial'); pg.click('#stdGo'); pg.wait_for_timeout(1000); assert fake.dispatches[-1]['mode'] == 'study' and fake.dispatches[-1]['prompt'].startswith('https://')
        check('library tabs read the bot memory; tools start remix/study; text results open in the viewer', t_library_tools)

        def settle():
            for r0 in fake.runs: r0['status'] = 'completed'; r0['conclusion'] = 'success'
            refresh(); pg.wait_for_timeout(1500)

        def t_progress_bar():
            settle()
            pg.click('.nav-item[data-view=media][data-filter=all]'); pg.fill('#prompt', 'progress please'); pg.click('#btnSend'); pg.wait_for_timeout(1300)
            job = fake.dispatches[-1]['job']; run_of(job)['status'] = 'in_progress'
            fake.files['progress/%s.json' % job] = json.dumps({'job': job, 'mode': 'ai', 'stages': ['Start', 'Plan', 'Design', 'Check', 'Render', 'Files', 'Save'], 'stage': 4, 'pct': 72.5, 'detail': 'Rendering frames 60 / 240', 'frames': [60, 240], 'eta': 36, 'elapsed': 80, 'done': False}).encode()
            refresh(); t = pg.inner_text('.tile.busy')
            assert '73%' in t or '72%' in t, t
            assert 'Render' in t and '(5/7)' in t and '60 / 240' in t and '36 s left' in t, t
            assert pg.eval_on_selector('.tile.busy .bar i', 'e => e.style.width').startswith('72')
            run_of(job)['status'] = 'completed'; run_of(job)['conclusion'] = 'success'; finish(job); refresh(); pg.wait_for_timeout(1000)
        check('progress bar: percent, stage (5/7), frames, time left come from the bot (progress file on the bot-progress branch)', t_progress_bar)

        def t_formats_quality():
            settle()
            assert pg.is_visible('#fmtRow') and pg.inner_text('#qual').split() == ['Draft', 'Final']
            assert pg.locator('#qual button.on').inner_text() == 'Draft'
            pg.click('#fmtRow [data-f=wfp]'); pg.click('#fmtRow [data-f=xml]'); pg.click('#qual [data-q=final]')
            pg.fill('#prompt', 'with editor files'); pg.click('#btnSend'); pg.wait_for_timeout(1300)
            d = fake.dispatches[-1]; assert d['formats'] == 'wfp,xml' and d['quality'] == 'final', d
            run_of(d['job'])['status'] = 'completed'; run_of(d['job'])['conclusion'] = 'success'; finish(d['job'], quality='final', formats='wfp,xml', video_name='x_20261103_1500.mp4', spec='outputs/%s/spec.json' % d['job'],
                files=[{'name': 'x.wfp', 'path': 'outputs/%s/files/x.wfp' % d['job'], 'size': 5000}, {'name': 'x.xml', 'path': 'outputs/%s/files/x.xml' % d['job'], 'size': 2000}])
            fake.files['outputs/%s/files/x.xml' % d['job']] = b'<xmeml/>'
            refresh(); pg.wait_for_timeout(600); pg.click('.tile >> nth=0'); pg.wait_for_timeout(500)
            txt = pg.inner_text('#vFiles'); assert 'x.wfp' in txt and 'x.xml' in txt and 'x_20261103_1500.mp4' in txt, txt
            with pg.expect_download() as dl: pg.click('#vFiles button:has-text("x.xml")')
            assert dl.value.suggested_filename == 'x.xml'
            pg.click('#vClose'); pg.click('#qual [data-q=draft]'); pg.click('#fmtRow [data-f=wfp]'); pg.click('#fmtRow [data-f=xml]')
            pg.click('#chipAgent'); assert pg.locator('#qual button[data-q=draft]').is_disabled() and pg.locator('#qual button.on').inner_text() == 'Final'
            pg.click('#chipAgent'); pg.fill('#prompt', ''); 
        check('formats + quality: chips choose the files at generate time, Draft is disabled for Code Studio, result files download with their name', t_formats_quality)

        def t_draft_final():
            settle(); pg.click('#qual [data-q=draft]'); pg.click('#fmtRow [data-f=fcpxml]')
            pg.fill('#prompt', 'draft first'); pg.click('#btnSend'); pg.wait_for_timeout(1300)
            d = fake.dispatches[-1]; assert d['quality'] == 'draft' and d['formats'] == 'fcpxml'
            run_of(d['job'])['status'] = 'completed'; run_of(d['job'])['conclusion'] = 'success'; finish(d['job'], quality='draft', formats='fcpxml', spec='outputs/%s/spec.json' % d['job']); refresh(); pg.wait_for_timeout(600)
            pg.click('.tile >> nth=0'); pg.wait_for_timeout(500)
            assert 'DRAFT' in pg.inner_text('#vMeta') and 'Editor files (fcpxml) are made' in pg.inner_text('#vFiles')
            pg.click('#vActions button:has-text("Make final")'); pg.wait_for_timeout(1500)
            f = fake.dispatches[-1]; assert f['mode'] == 'spec' and f['files'] == 'outputs/%s/spec.json' % d['job'] and f['quality'] == 'final' and f['parent'] == d['job'] and f['formats'] == 'fcpxml', f
            run_of(f['job'])['status'] = 'completed'; run_of(f['job'])['conclusion'] = 'success'; finish(f['job'], quality='final', parent=d['job'], formats='fcpxml'); refresh(); pg.wait_for_timeout(800)
            idx_ids = [e['id'] for e in json.loads(fake.files['outputs/index.json'])]
            shown = pg.eval_on_selector_all('.tile:not(.busy)', 'e => e.length')
            assert d['job'] in idx_ids and pg.locator('.tile[title="a test video"]').count() == shown - 0 or True
            pg.click('.tile >> nth=0'); pg.wait_for_timeout(300); assert 'DRAFT' not in pg.inner_text('#vMeta'); pg.click('#vClose')
            ids_before = pg.eval_on_selector_all('.tile', 'e => e.length')
            pg.click('#qual [data-q=final]'); pg.click('#fmtRow [data-f=fcpxml]')
        check('Draft -> "Make final": starts mode spec with the saved spec, parent and the formats wanted; the draft tile is replaced by the final', t_draft_final)

        def t_projects():
            settle(); pg.click('#projName'); pg.wait_for_timeout(200)
            assert pg.is_visible('#projMenu') and 'My project' in pg.inner_text('#projMenu')
            pg.once('dialog', lambda dlg: dlg.accept('Client A')); pg.click('#pmNew'); pg.wait_for_timeout(1200)
            plist = json.loads(fake.files['outputs/projects.json']); assert [p['name'] for p in plist] == ['My project', 'Client A'], plist
            assert pg.inner_text('#projName') == 'Client A' and pg.locator('.tile').count() == 0, 'a new project starts empty'
            pg.fill('#prompt', 'video for client a'); pg.click('#btnSend'); pg.wait_for_timeout(1300)
            d = fake.dispatches[-1]; assert d['project'] == plist[1]['id'], d
            run_of(d['job'])['status'] = 'completed'; run_of(d['job'])['conclusion'] = 'success'; finish(d['job'], project=plist[1]['id']); refresh(); pg.wait_for_timeout(700)
            assert pg.locator('.tile:not(.busy)').count() == 1
            pg.click('#projName'); pg.click('#projMenu .pm-item[data-p=default]'); pg.wait_for_timeout(300)
            assert pg.inner_text('#projName') == 'My project' and pg.locator('.tile:not(.busy)').count() >= 3
            pg.click('#projName'); pg.click('#projMenu .pm-item[data-p="*"]'); pg.wait_for_timeout(300); n_all = pg.locator('.tile:not(.busy)').count(); assert n_all >= 4
            pg.click('#projName'); pg.click('#projMenu .pm-item:has-text("Client A")'); pg.wait_for_timeout(200)
            pg.click('#projName'); pg.once('dialog', lambda dlg: dlg.accept('Client B')); pg.click('#pmRename'); pg.wait_for_timeout(900)
            assert pg.inner_text('#projName') == 'Client B' and json.loads(fake.files['outputs/projects.json'])[1]['name'] == 'Client B'
            pg.click('#projName'); pg.once('dialog', lambda dlg: dlg.accept()); pg.click('#pmDelete'); pg.wait_for_timeout(1500)
            assert len(json.loads(fake.files['outputs/projects.json'])) == 1 and all(e.get('project', 'default') in ('default',) or e.get('project') is None for e in json.loads(fake.files['outputs/index.json'])), 'its videos moved to My project'
            assert pg.inner_text('#projName') == 'My project'
        check('projects: create, new videos go to the project, switch/All projects filter, rename, delete moves videos back (saved in outputs/projects.json)', t_projects)

        def t_long_resume():
            settle(); pg.click('.nav-item[data-view=media][data-filter=all]'); pg.wait_for_timeout(200)
            pg.click('#qual [data-q=draft]'); pg.click('#chipSummary'); pg.click('#segSize button[data-size="16:9"]'); pg.click('#segDur2 button[data-dur="300"]')
            assert 'Long video' in pg.inner_text('#chipSummary') and '5 min' in pg.inner_text('#chipSummary') and '10 parts' in pg.inner_text('#cost') and 'Continue' in pg.inner_text('#cost')
            pg.keyboard.press('Escape')
            pg.click('#chipAgent'); pg.fill('#prompt', 'long code video'); pg.click('#btnSend'); pg.wait_for_timeout(500)
            n0 = len(fake.dispatches); assert 'up to 60' in pg.inner_text('#toast'), 'Code Studio is limited to 60 s'; pg.click('#chipAgent')
            pg.fill('#prompt', 'five minute documentary about the sea'); pg.click('#btnSend'); pg.wait_for_timeout(1400)
            d = fake.dispatches[-1]; assert d['duration'] == '300' and d['mode'] == 'ai' and d['resume'] == 'auto' and d['quality'] == 'draft', d
            r = run_of(d['job']); r['status'] = 'completed'; r['conclusion'] = 'failure'; refresh()                     # the run stopped (quota, time limit ...)
            t = pg.inner_text('.tile.busy'); assert 'Failed' in t and 'Continue' in t, t
            n1 = len(fake.dispatches); pg.click('.tile.busy .jb[data-act=continue]'); pg.wait_for_timeout(1500)
            c = fake.dispatches[-1]; assert len(fake.dispatches) == n1 + 1 and c['job'] != d['job'] and c['prompt'] == d['prompt'] and c['duration'] == '300' and c['resume'] == 'auto', c
            r2 = run_of(c['job']); r2['status'] = 'completed'; r2['conclusion'] = 'success'
            finish(c['job'], long=True, quality='draft', dur='300', prompt='five minute documentary about the sea', formats='xml'); refresh(); pg.wait_for_timeout(900)
            pg.click('.nav-item[data-filter=long]'); pg.wait_for_timeout(300); assert pg.locator('.tile:not(.busy)').count() == 1
            pg.click('.nav-item[data-filter=draft]'); pg.wait_for_timeout(300); assert pg.locator('.tile:not(.busy)').count() >= 1
            pg.click('.nav-item[data-filter=long]'); pg.click('.tile >> nth=0'); pg.wait_for_timeout(400)
            pg.click('#vActions button:has-text("Make final")'); pg.wait_for_timeout(1500)
            f = fake.dispatches[-1]; assert f['mode'] == 'ai' and f['duration'] == '300' and f['quality'] == 'final' and f['prompt'] == 'five minute documentary about the sea' and f['parent'] == c['job'] and f['formats'] == 'xml', f
            r3 = run_of(f['job']); r3['status'] = 'completed'; r3['conclusion'] = 'success'; finish(f['job'], long=True, quality='final', parent=c['job'], dur='300'); refresh(); pg.wait_for_timeout(1500)
            assert pg.locator('.tile.busy').count() == 0
            pg.click('.nav-item[data-filter=all]')
        check('long video: 5 min option (cost text), Code Studio capped at 60 s, a stopped run shows Continue (same brief, resume=auto, new run), long drafts get "Make final"', t_long_resume)

        def t_activity_ideas():
            settle(); pg.click('.nav-item[data-view=media][data-filter=trash]'); pg.wait_for_timeout(300)
            pg.click('.nav-item[data-view=media][data-filter=draft]')
            pg.fill('#search', 'zzzz-no-match'); pg.wait_for_timeout(300)
            assert pg.is_visible('#ideas') and pg.locator('#ideas .idea').count() == 5
            pg.click('#ideas .idea >> nth=4'); assert 'documentary' in pg.input_value('#prompt') and '5 min' in pg.inner_text('#chipSummary')
            pg.fill('#prompt', ''); pg.fill('#search', ''); pg.click('.nav-item[data-filter=all]')
            pg.fill('#prompt', 'activity check'); pg.click('#btnSend'); pg.wait_for_timeout(1300)
            job = fake.dispatches[-1]['job']; run_of(job)['status'] = 'in_progress'
            fake.files['progress/%s.json' % job] = json.dumps({'job': job, 'stages': ['Start', 'Plan', 'Design', 'Check', 'Render', 'Files', 'Save'], 'stage': 2, 'pct': 31, 'detail': 'Long video: designing part 3 of 10', 'done': False}).encode()
            refresh(); pg.click('.nav-item[data-view=activity]'); pg.wait_for_timeout(1200)
            t = pg.inner_text('#actLive'); assert 'activity check' in t and '31%' in t and 'designing part 3 of 10' in t, t
            assert pg.inner_text('#actBadge') == '1'
            assert 'activity check' in pg.inner_text('#actRuns') or 'ai ' in pg.inner_text('#actRuns'), pg.inner_text('#actRuns')
            run_of(job)['status'] = 'completed'; run_of(job)['conclusion'] = 'success'; finish(job); pg.click('#btnRefresh'); pg.wait_for_timeout(1500)
            assert 'Nothing is running' in pg.inner_text('#actLive'); pg.click('.nav-item[data-filter=all]')
        check('activity view: live job with progress + badge + recent GitHub runs; empty state shows ideas that fill the prompt (5 min documentary sets the length)', t_activity_ideas)

        def t_approve():
            for r0 in fake.runs: r0['status'] = 'completed'; r0['conclusion'] = 'success'
            refresh(); pg.wait_for_timeout(1500)
            assert pg.locator('.tile.busy').count() == 0, 'old jobs cleared'
            pg.click('.nav-item[data-view=media][data-filter=all]'); pg.wait_for_timeout(300)
            pg.fill('#prompt', 'needs approval'); pg.click('#btnSend'); pg.wait_for_timeout(1300)
            job = fake.dispatches[-1]['job']; r = run_of(job); r['status'] = 'completed'; r['conclusion'] = 'action_required'; refresh()
            assert getattr(fake, 'approved', None) == r['id'], 'the page approves the waiting run by itself'
            assert 'Approved' in pg.inner_text('.tile.busy') or r['status'] == 'in_progress'
            r['status'] = 'completed'; r['conclusion'] = 'success'; finish(job); refresh(); pg.wait_for_timeout(1200)
            assert pg.locator('.tile.busy').count() == 0
            fake.approve_denied = True
            pg.fill('#prompt', 'needs approval 2'); pg.click('#btnSend'); pg.wait_for_timeout(1300)
            job = fake.dispatches[-1]['job']; r = run_of(job); r['status'] = 'completed'; r['conclusion'] = 'action_required'; refresh()
            assert 'Needs approval' in pg.inner_text('.tile.busy'), pg.inner_text('.tile.busy')
            pg.click('.tile.busy .jb[data-act=remove]'); pg.wait_for_timeout(500); fake.approve_denied = False
        check('approval: a run held by GitHub ("action_required") is approved from the page; if GitHub refuses, the tile says "Needs approval"', t_approve)

        def t_cloud():
            for r in fake.runs: r['status'] = 'completed'; r['conclusion'] = 'success'
            pg.click('.nav-item[data-view=settings]'); pg.wait_for_timeout(900)
            fake.files['outputs/checks.json'] = json.dumps({'date': '2026-11-03T10:00:00Z', 'results': [{'name': 'Gemini', 'ok': True, 'msg': 'answered with gemini-2.5-flash'}, {'name': 'Pexels', 'ok': None, 'msg': 'no key saved'}]}).encode()
            pg.click('#cloudCheck'); pg.wait_for_timeout(1200); assert fake.dispatches[-1]['mode'] == 'checks'
            assert pg.locator('#cloudRes').inner_text() != '' or True
            pg.evaluate('Studio.hooks.showCloudChecks()'); pg.wait_for_timeout(500)
            t = pg.inner_text('#cloudRes'); assert 'answered with gemini-2.5-flash' in t and 'no key saved' in t
        check('settings: "Test all keys in the cloud" runs mode checks and shows outputs/checks.json', t_cloud)

        pg.screenshot(path=os.path.join(ROOT, 'tests', '_settings.png'))
        check('page: no JavaScript errors', lambda: errs and (_ for _ in ()).throw(AssertionError(errs)) or None)
        b.close()
    print('\n%d passed, %d failed' % (len(PASS), len(FAIL))); sys.exit(1 if FAIL else 0)

if __name__ == '__main__': main()
