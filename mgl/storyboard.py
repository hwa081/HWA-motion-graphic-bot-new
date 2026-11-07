"""mgl.storyboard - read the finished design (script -> scenes) and show the WHOLE video as ONE picture before any video is made.

One tile per scene (the moment when most of the scene is on screen), with the scene number, the time and what is written in it.
The user looks at the picture, then presses "Approve" (the video is made) or throws it away (nothing was wasted).
"""
import json, os
import numpy as np, cv2
from PIL import Image, ImageDraw
from . import engine as E, spec as S

BACKDROP = ('grid', 'particles', 'blob', 'transition', 'line')


def _cuts(spec):
    try:
        return sorted({float(b['t']) for b in spec.get('background', []) if isinstance(b, dict) and float(b.get('t', 0)) > 0.4})
    except Exception:
        return []


def _visible(spec, t):
    return [L for L in spec.get('layers', []) if isinstance(L, dict) and float(L.get('start', 0)) <= t <= float(L.get('end', spec['duration']))]


def _label(L):
    if L.get('type') == 'text': return str(L.get('text', '')).replace('{n}', '').replace('\n', ' ').strip()
    return {'chart': 'chart', 'device': 'device', 'card': 'card', 'chip': str(L.get('label', 'chip')), 'image': 'image', 'progress': 'progress', 'pen': 'drawing', 'icon': 'icon'}.get(L.get('type'), '')


def shots(spec, max_n=12, voice=None):
    dur = float(spec['duration'])
    cuts = [c for c in _cuts(spec) if c < dur - 0.4]
    bounds = [0.0] + cuts + [dur]
    if voice and voice.get('segments'):                          # with a voice-over the scenes ARE its sentences
        bounds = sorted({0.0, dur} | {float(s['start']) for s in voice['segments'] if 0 < float(s['start']) < dur - 0.4})
    elif len(bounds) - 1 < 3:                                   # no scene markers: cut where new things start
        starts = sorted({round(float(L.get('start', 0)), 1) for L in spec.get('layers', []) if isinstance(L, dict) and L.get('type') not in BACKDROP and float(L.get('start', 0)) > 0.3})
        n = int(min(8, max(3, round(dur / 3.0))))
        bounds = [0.0] + [dur * i / n for i in range(1, n)] + [dur]
        if starts and len(starts) >= 2:
            pick = [starts[int(i * len(starts) / n)] for i in range(1, n) if int(i * len(starts) / n) < len(starts)]
            bounds = sorted(set([0.0] + [p for p in pick if 0.3 < p < dur - 0.3] + [dur]))
    sub = [bounds[0]]
    for a, b in zip(bounds, bounds[1:]):                        # a long scene shows several moments
        if voice: sub.append(b); continue
        k = int(min(3, max(1, round((b - a) / 3.2))))
        sub += [a + (b - a) * j / k for j in range(1, k)] + [b]
    bounds = sub
    while len(bounds) - 1 > max_n:                             # too many scenes: merge the shortest
        gaps = [(bounds[i + 1] - bounds[i], i) for i in range(1, len(bounds) - 1)]
        bounds.pop(min(gaps)[1])
    out = []
    for a, b in zip(bounds, bounds[1:]):
        cands = [a + (b - a) * f for f in (0.55, 0.75, 0.9)]
        best = max(cands, key=lambda t: (len([L for L in _visible(spec, t) if L.get('type') not in BACKDROP]), t))
        vis = [L for L in _visible(spec, best) if L.get('type') not in BACKDROP]
        words, cnt = [], {}
        for w in (_label(L) for L in vis):
            if w: cnt[w] = cnt.get(w, 0) + 1
        words = [w if c == 1 else '%s x%d' % (w, c) for w, c in cnt.items()]
        said = next((x.get('text', '') for x in (voice or {}).get('segments', []) if x['start'] - 0.05 <= a < x['end']), '')
        out.append({'t0': round(a, 2), 't1': round(b, 2), 't': round(best, 2), 'text': ' / '.join(words)[:70], 'layers': len(vis), 'said': said[:90]})
    return out


def build(spec, out_png, ctx, max_n=12, voice=None):
    """-> list of shots (also written next to the picture as storyboard.json)"""
    S.setup(spec)
    sh = shots(spec, max_n, voice)
    cols = 3 if len(sh) > 4 or E.W >= E.H else 4
    cols = min(cols, len(sh)) if len(sh) < cols else cols
    tw = 560 if E.W >= E.H else 300
    th = int(tw * E.H / E.W); cap_h = 92 if voice else 64
    tiles = []
    font = E.font(E.font_path('bold'), 22); small = E.font(E.font_path('regular'), 18)
    for i, s in enumerate(sh):
        fr = S.render_frame(spec, s['t'], ctx)
        fr = cv2.resize(fr, (tw, th), interpolation=cv2.INTER_AREA)
        tile = Image.new('RGB', (tw, th + cap_h), (18, 20, 26)); tile.paste(Image.fromarray(np.ascontiguousarray(fr)), (0, 0))
        d = ImageDraw.Draw(tile)
        d.text((10, th + 6), 'Scene %d   %.1fs - %.1fs' % (i + 1, s['t0'], s['t1']), fill=(255, 220, 90), font=font)
        txt = s['text'] or '(no text)'
        d.text((10, th + 34), ('On screen: ' + txt)[:52], fill=(215, 218, 226), font=small)
        if s.get('said'): d.text((10, th + 60), ('Voice: ' + s['said'])[:52], fill=(150, 220, 170), font=small)
        d.rectangle([0, 0, tw - 1, th + cap_h - 1], outline=(60, 64, 74))
        tiles.append(np.array(tile))
    while len(tiles) % cols: tiles.append(np.full_like(tiles[0], 12))
    sheet = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    Image.fromarray(sheet).save(out_png, optimize=True)
    json.dump({'duration': spec['duration'], 'shots': sh}, open(os.path.splitext(out_png)[0] + '.json', 'w'), ensure_ascii=False, indent=1)
    return sh
