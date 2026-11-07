"""Where does the time go? Counts AI calls, AI waiting (rate limits / retries), rendering and file making, then writes a short table
(out/timing.md + out/timing.json) so a slow run can be understood instead of guessed. Never raises."""
import json, os, threading, time
from contextlib import contextmanager

_lock = threading.Lock()
_t0 = time.time()
_ev = []          # (kind, seconds, note)


def reset():
    global _t0
    with _lock:
        _t0 = time.time(); del _ev[:]


def add(kind, seconds, note=''):
    with _lock:
        _ev.append((kind, float(seconds), str(note)[:120]))


@contextmanager
def span(kind, note=''):
    t = time.time()
    try:
        yield
    finally:
        add(kind, time.time() - t, note)


def summary():
    with _lock:
        ev = list(_ev); total = time.time() - _t0
    def tot(k): return round(sum(s for kk, s, _ in ev if kk == k), 1)
    def cnt(k): return sum(1 for kk, _, _ in ev if kk == k)
    slow = sorted([e for e in ev if e[0] == 'ai_call'], key=lambda e: -e[1])[:3]
    return {'total_s': round(total, 1), 'ai_requests': cnt('ai_request'), 'ai_request_s': tot('ai_request'), 'ai_http_calls': cnt('ai_call'), 'ai_http_s': tot('ai_call'),
            'ai_wait_s': tot('ai_wait'), 'ai_failed_calls': sum(1 for k, _, n in ev if k == 'ai_call' and n.startswith('fail')),
            'design_s': tot('design'), 'render_s': tot('render'), 'files_s': tot('files'), 'sound_s': tot('sound'),
            'slowest_ai_calls': [{'s': round(s, 1), 'note': n} for _, s, n in slow]}


def report_md(s=None):
    s = s or summary(); m = lambda x: '%.1f min' % (x / 60.0) if x >= 90 else '%.0f s' % x
    other = max(0.0, s['total_s'] - s['ai_request_s'] - s['render_s'] - s['files_s'] - s['sound_s'])
    L = ['## Where the time went', '', '| Step | Time |', '|---|---|',
         '| Whole run (after setup) | %s |' % m(s['total_s']),
         '| AI: %d requests (%d HTTP calls, %d failed / rate-limited) | %s |' % (s['ai_requests'], s['ai_http_calls'], s['ai_failed_calls'], m(s['ai_request_s'])),
         '|   of which waiting for rate limits / retries | %s |' % m(s['ai_wait_s']),
         '| Rendering frames + encoding | %s |' % m(s['render_s']),
         '| Sound | %s |' % m(s['sound_s']),
         '| Editor files and other exports | %s |' % m(s['files_s']),
         '| Everything else (checks, drawing helpers, saving) | %s |' % m(other)]
    if s['slowest_ai_calls']: L += ['', 'Slowest AI calls: ' + ', '.join('%s (%s)' % (m(x['s']), x['note']) for x in s['slowest_ai_calls'])]
    if s['ai_request_s'] > 0.5 * max(1.0, s['total_s']) and s['ai_wait_s'] > 0.3 * s['ai_request_s']:
        L += ['', '**Most of the time went to waiting for the AI (rate limits).** A second key or a lighter model setting will help more than a faster render.']
    return '\n'.join(L) + '\n'


def write(out_dir):
    try:
        s = summary(); os.makedirs(out_dir, exist_ok=True)
        json.dump(s, open(os.path.join(out_dir, 'timing.json'), 'w'), indent=1)
        open(os.path.join(out_dir, 'timing.md'), 'w', encoding='utf-8').write(report_md(s))
        print('[time] total %.0fs | AI %.0fs (%d requests, waiting %.0fs) | render %.0fs | files %.0fs | sound %.0fs' % (
            s['total_s'], s['ai_request_s'], s['ai_requests'], s['ai_wait_s'], s['render_s'], s['files_s'], s['sound_s']), flush=True)
        return s
    except Exception as ex:
        print('timing not written: %s' % ex); return None
