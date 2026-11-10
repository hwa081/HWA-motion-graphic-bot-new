import sys, os, time, json, tempfile, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from mgl import longform
import render as R
R.render_video = lambda sp, out, ctx, quiet=True: open(out, 'wb').write(b'x')
longform.concat_videos = lambda v, out: open(out, 'wb').write(b'x')
class W:  # worker provider
    def __init__(s, i): s.id = i; s.name = i.upper(); s.model = 'm-' + i
def fake_ask(system, contents, json_mode=True):
    return json.dumps({'title': 't', 'parts': [{'title': 'p%d' % i, 'brief': 'b', 'seconds': 10} for i in range(5)]})
fake_ask.calls = 0
fake_ask.pinned = lambda pid: types.SimpleNamespace(pid=pid)
fake_ask.workers = lambda: [W('a'), W('b'), W('c')]
done_by = {}
class AG:
    @staticmethod
    def run_agent(prompt, sec, out, askx, **kw):
        pid = getattr(askx, 'pid', 'chain')
        if pid == 'b': raise RuntimeError('quota exceeded')
        time.sleep(0.1)
        done_by[prompt[:40]] = pid
        return {'duration': sec, 'layers': [], 'background': 'solid'}
logs = []
d = tempfile.mkdtemp()
r = longform.run_long('hindi script', 50, os.path.join(d, 'o'), fake_ask, root=d, log=logs.append, sound='none', agent_mod=AG, resume=False)
print('\n'.join(l for l in logs if l.startswith(('[team', '[ai', '[part'))))
print(sorted(set(done_by.values())), r['parts'])
assert 'b' not in done_by.values() and r['parts'] == 5
