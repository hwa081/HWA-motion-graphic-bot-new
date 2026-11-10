import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from mgl.memory import Memory
d = tempfile.mkdtemp()
m = Memory(d)
n = len(m.styles); assert n >= 10, n
assert len(m.notebook['techniques']) >= 10 and 'SOUND' in m.style_guide()
m.save(); m2 = Memory(d)
assert len(m2.styles) == n and len(m2.notebook['techniques']) == len(m.notebook['techniques'])     # added once, not doubled
ctx = m2.context_for_prompt('saas product promo with typing and whoosh sounds')
assert 'STYLE GUIDE' in ctx and len(ctx) <= 8000
print('ok', n, len(m2.notebook['techniques']), len(ctx))
