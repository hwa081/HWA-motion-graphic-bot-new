"""Pen tool (like Filmora's): free-form bezier paths that draw themselves on.

A spec layer  {"type": "pen", "path": [...anchors...], "closed": true, "color": c, "width": 8, "fill": c, "draw": {...}}
  anchor  = [x, y]                       corner point
          | [x, y, lx, ly, rx, ry]       smooth point: (lx,ly) = handle towards the previous point, (rx,ry) = handle towards the next one
  all numbers are canvas pixels (1920x1080 for 16:9); "norm": true means 0..1 instead.

What it learned from the Filmora pen projects (pen_demo2.wfp, ai_to_native_kinetic_typography.wfp):
  * a pen layer = path points (value_x/value_y 0..1, handles left_ctrl_point/right_ctrl_point) + stroke (colour, size, round caps)
    + fill (flat or gradient, alpha, blur) + trim (path_trim end 0..100 = the line "draws itself") + drop shadow
  * the layer itself has transform (scale / rotation about the canvas centre) and opacity keyframes
  * times are in 1/10,000,000 s units, colours are BGR integers, keyframe times inside effects are seconds
`from_wfp()` reads those projects back into spec layers, `to_native()` writes spec pen layers as real, editable Filmora pen clips.
"""
import json, math, zipfile
import numpy as np, cv2
from . import engine as E

SEG_MIN, SEG_MAX = 8, 64


# ------------------------------------------------------------------ geometry
def anchors(path, norm=False, size=None):
    """-> list of (p, l, r) with p, l, r = (x, y); l / r are None for corners. Raises ValueError on bad input."""
    W, H = size or (E.W, E.H)
    sx, sy = (W, H) if norm else (1.0, 1.0)
    out = []
    if not isinstance(path, (list, tuple)) or len(path) < 2: raise ValueError('path needs at least 2 points')
    for a in path:
        if isinstance(a, dict):
            p = (float(a['x']) * sx, float(a['y']) * sy)
            l = tuple(float(v) * s for v, s in zip(a['l'], (sx, sy))) if a.get('l') else None
            r = tuple(float(v) * s for v, s in zip(a['r'], (sx, sy))) if a.get('r') else None
        else:
            if len(a) not in (2, 6): raise ValueError('a point is [x, y] or [x, y, lx, ly, rx, ry]')
            v = [float(q) for q in a]
            p = (v[0] * sx, v[1] * sy)
            l = (v[2] * sx, v[3] * sy) if len(v) == 6 else None
            r = (v[4] * sx, v[5] * sy) if len(v) == 6 else None
        out.append((p, l, r))
    return out


def flatten(anc, closed):
    """sample the bezier segments -> (N, 2) float array. The closing segment is included when closed."""
    pts = []
    n = len(anc)
    segs = n if closed else n - 1
    for i in range(segs):
        p0, _, r0 = anc[i]; p3, l3, _ = anc[(i + 1) % n]
        p1 = r0 or p0; p2 = l3 or p3
        chord = math.dist(p0, p3) + math.dist(p0, p1) + math.dist(p2, p3)
        m = int(max(SEG_MIN, min(SEG_MAX, chord / 8)))
        for j in range(m):
            u = j / m; v = 1 - u
            pts.append((v ** 3 * p0[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u ** 3 * p3[0],
                        v ** 3 * p0[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u ** 3 * p3[1]))
    pts.append(anc[0][0] if closed else anc[-1][0])
    return np.array(pts, dtype=np.float64)


def trim_poly(pts, a, b):
    """part of the polyline between fraction a and b of its length"""
    if b <= a or len(pts) < 2: return pts[:0]
    if a <= 0 and b >= 1: return pts
    seg = np.hypot(*(pts[1:] - pts[:-1]).T)
    cum = np.concatenate([[0], np.cumsum(seg)]); tot = cum[-1]
    if tot <= 1e-9: return pts[:1]
    la, lb = a * tot, b * tot
    def at(d):
        i = int(min(np.searchsorted(cum, d, side='right') - 1, len(seg) - 1)); i = max(i, 0)
        u = 0 if seg[i] <= 1e-12 else (d - cum[i]) / seg[i]
        return pts[i] + (pts[i + 1] - pts[i]) * u
    inner = pts[(cum > la) & (cum < lb)]
    return np.vstack([at(la)[None], inner, at(lb)[None]])


def bbox(anc):
    xs = [q[0] for a in anc for q in a if q]; ys = [q[1] for a in anc for q in a if q]
    return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------------ drawing
def draw(f, L, S, anc, closed, transform, op):
    """f: float32 frame (H, W, 3), S: evaluated style dict (colours already tuples), transform: (pivot, ks, rot_deg, off, cam)
    pivot/off in world px, cam = (z, cx, cy)."""
    (px, py), ks, rot, (ox, oy), (z, cx, cy) = transform
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    def tf(q):
        dx, dy = (q[0] - px) * ks, (q[1] - py) * ks
        wx, wy = px + ca * dx - sa * dy + ox, py + sa * dx + ca * dy + oy
        return ((wx - cx) * z + E.W / 2, (wy - cy) * z + E.H / 2)
    anc2 = [(tf(p), tf(l) if l else None, tf(r) if r else None) for p, l, r in anc]
    pts = flatten(anc2, closed)
    k = ks * z
    width = max(0.0, S['width'] * k)
    glow = max(0.0, S.get('glow', 0) * k); sh = S.get('shadow', 0.0); shb = max(1.0, S.get('shadow_blur', 20) * k); shd = S.get('shadow_dy', 12) * k
    fblur = max(0.0, S.get('fill_blur', 0) * k)
    margin = int(width / 2 + 3 * max(glow, shb if sh > 0 else 0, fblur) + abs(shd) + 6)
    x0 = int(max(0, math.floor(pts[:, 0].min()) - margin)); y0 = int(max(0, math.floor(pts[:, 1].min()) - margin))
    x1 = int(min(E.W, math.ceil(pts[:, 0].max()) + margin)); y1 = int(min(E.H, math.ceil(pts[:, 1].max()) + margin))
    if x1 - x0 < 2 or y1 - y0 < 2: return
    h, w = y1 - y0, x1 - x0
    loc = (pts - np.array([x0, y0])) * 16
    loc = np.round(loc).astype(np.int32)

    fill_a = None
    if S.get('fill') is not None and S.get('fill_alpha', 0) > 0.003 and len(pts) >= 3:
        fill_a = np.zeros((h, w), np.float32)
        cv2.fillPoly(fill_a, [loc], 1.0, cv2.LINE_AA, 4)
        if fblur > 0.5: fill_a = cv2.GaussianBlur(fill_a, (0, 0), fblur)
        fill_a *= S['fill_alpha']
    stroke_a = None
    tp = trim_poly(pts, S.get('trim_start', 0.0), S.get('trim', 1.0))
    if width > 0.4 and len(tp) >= 1 and S.get('stroke_alpha', 1.0) > 0.003:
        stroke_a = np.zeros((h, w), np.float32)
        tl = np.round((tp - np.array([x0, y0])) * 16).astype(np.int32)
        th = max(1, int(round(width)))
        if len(tl) >= 2: cv2.polylines(stroke_a, [tl], False, 1.0, th, cv2.LINE_AA, 4)
        r16 = int(round(width / 2 * 16))
        if r16 > 0:       # round caps and joins
            for q in ([tl[0], tl[-1]] + [np.round((np.array(a[0]) - np.array([x0, y0])) * 16).astype(np.int32) for a in anc2 if len(tl) >= 2 and _near(tp, a[0])]):
                cv2.circle(stroke_a, (int(q[0]), int(q[1])), r16 // 16 if r16 >= 16 else 1, 1.0, -1, cv2.LINE_AA, 0) if False else cv2.circle(stroke_a, (int(q[0]), int(q[1])), max(1, r16), 1.0, -1, cv2.LINE_AA, 4)
        stroke_a *= S.get('stroke_alpha', 1.0)
    if fill_a is None and stroke_a is None: return

    acc_rgb = np.zeros((h, w, 3), np.float32); acc_a = np.zeros((h, w), np.float32)
    def put(a, rgb):
        a3 = a[..., None]
        acc_rgb[:] = acc_rgb * (1 - a3) + np.asarray(rgb, np.float32) * a3
        acc_a[:] = acc_a * (1 - a) + a
    union = None
    for m in (fill_a, stroke_a):
        if m is not None: union = m if union is None else np.maximum(union, m)
    if sh > 0.003:
        s = cv2.GaussianBlur(union, (0, 0), shb / 2)
        s = np.roll(s, int(round(shd)), axis=0) if abs(shd) >= 1 else s
        put(np.clip(s * sh, 0, 1), S.get('shadow_color', (0, 0, 0)))
    if glow > 0.5 and stroke_a is not None:
        put(np.clip(cv2.GaussianBlur(stroke_a, (0, 0), glow) * 1.6, 0, 1) * 0.8, S['color'])
    if fill_a is not None:
        c1 = np.asarray(S['fill'], np.float32)
        if S.get('fill2') is not None:
            c2 = np.asarray(S['fill2'], np.float32)
            ys = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
            fc = c1 * (1 - ys) + c2 * ys
            fc = np.broadcast_to(fc, (h, w, 3))
            a3 = fill_a[..., None]
            acc_rgb[:] = acc_rgb * (1 - a3) + fc * a3; acc_a[:] = acc_a * (1 - fill_a) + fill_a
        else:
            put(fill_a, c1)
    if stroke_a is not None: put(stroke_a, S['color'])
    E.over(f, acc_rgb, acc_a, x0, y0, op)


def _near(poly, p, tol=2.5):
    d = np.hypot(poly[:, 0] - p[0], poly[:, 1] - p[1])
    return bool(d.min() < tol)


# ------------------------------------------------------------------ Filmora import / export
U = 10000000.0          # Filmora time unit (1/10,000,000 s)


def _bgr_hex(v):
    v = int(v); return '#%02x%02x%02x' % (v & 255, (v >> 8) & 255, (v >> 16) & 255)


def _kf(s):
    """Filmora keyframe string -> [(time, value)] (time as stored)"""
    try: return [(float(k['_time']), float(k['_value'])) for k in json.loads(s)['keyframeSets']]
    except Exception: return []


def _fx(clip, name):
    for ch in clip.get('effectChainList', []):
        for e in ch.get('effectList', []):
            if e.get('display') == name: return e
    return None


def _prm(e, name, default=None):
    if not e: return default
    for p in e.get('paramList', []):
        if p['name'] == name: return p['fxParam'].get('unValue', default)
    return default


def _map(e, name):
    if not e: return []
    for m in e.get('paramMapList') or []:
        if m['name'] == name: return _kf(m['keyFrame']['parameter'])
    return []


def from_wfp(path):
    """read a Filmora .wfp: every pen clip becomes a spec layer. -> {'size': [w, h], 'duration': s, 'layers': [...]}"""
    z = zipfile.ZipFile(path)
    wes = json.loads(z.read(next(n for n in z.namelist() if n.endswith('timeline.wesproj'))).decode('utf-8'))
    ti = next(t for t in wes['timelineInfos'] if t['timelineId'] == wes['currentTimelineId'])
    W, H = float(ti.get('resolutionWidth', 1920)), float(ti.get('resolutionHeight', 1080))
    layers, dur = [], 0.0
    for tr in ti['trackInfos']:
        for c in tr.get('clipList', []):
            dur = max(dur, c['tlEnd'] / U)
            if c.get('serviceType') != 'pen': continue
            L = _clip_to_layer(c, W, H)
            if L: layers.append(L)
    return {'size': [int(W), int(H)], 'duration': round(dur, 3), 'layers': layers}


def _clip_to_layer(c, W, H):
    s, e = c['tlBegin'] / U, c['tlEnd'] / U
    L = {'start': round(s, 3), 'end': round(e, 3)}
    rect = _fx(c, 'path_graphic_rect')
    path = _fx(c, 'path')
    fill = _fx(c, 'path_fill'); stroke = _fx(c, 'path_stroke'); trim = _fx(c, 'path_trim'); shadow = _fx(c, 'path_dropshadow'); tr = _fx(c, 'transform')
    if rect is not None:
        w, h = _prm(rect, 'width', 1.0), _prm(rect, 'height', 1.0)
        L.update({'type': 'rrect', 'x': round(W * (_prm(rect, 'start_x', 0) + w / 2), 1), 'y': round(H * (_prm(rect, 'start_y', 0) + h / 2), 1),
                  'w': round(w * W, 1), 'h': round(h * H, 1), 'r': 0, 'fill': _bgr_hex(_prm(fill, 'color', 0xFFFFFF))})
    elif path is not None and path.get('effectMask'):
        try: pj = json.loads(path['effectMask']['custom_mask'])['paths'][0]
        except Exception: return None
        pts = []
        for q in pj['points']:
            x, y = q['value_x'] * W, q['value_y'] * H
            lc, rc = q.get('left_ctrl_point'), q.get('right_ctrl_point')
            if lc or rc:
                lc = lc or {'value_x': q['value_x'], 'value_y': q['value_y']}; rc = rc or {'value_x': q['value_x'], 'value_y': q['value_y']}
                pts.append([round(x, 1), round(y, 1), round(lc['value_x'] * W, 1), round(lc['value_y'] * H, 1), round(rc['value_x'] * W, 1), round(rc['value_y'] * H, 1)])
            else: pts.append([round(x, 1), round(y, 1)])
        L.update({'type': 'pen', 'path': pts, 'closed': bool(pj.get('is_closed', True))})
        lw = _prm(stroke, 'lineSize', 0); sa = _prm(stroke, 'alpha', 100) / 100.0
        if lw and sa > 0: L.update({'color': _bgr_hex(_prm(stroke, 'color', 0xFFFFFF)), 'width': float(lw)})
        else: L['width'] = 0
        if sa < 1 and L['width']: L['stroke_opacity'] = round(sa, 2)
        fa = _prm(fill, 'alpha', 100) / 100.0
        if fa > 0:
            L['fill'] = _bgr_hex(_prm(fill, 'colorStart', _prm(fill, 'color', 0xFFFFFF))); L['fill_opacity'] = round(fa, 2)
            if _prm(fill, 'colorEnd') is not None and _prm(fill, 'fillType', 0) == 1: L['fill2'] = _bgr_hex(_prm(fill, 'colorEnd'))
            if _prm(fill, 'blur', 0): L['fill_blur'] = float(_prm(fill, 'blur'))
        if shadow is not None and _prm(shadow, 'alpha', 0) > 0:
            L.update({'shadow': round(_prm(shadow, 'alpha') / 100.0, 2), 'shadow_blur': float(_prm(shadow, 'blur', 20)),
                      'shadow_dy': float(_prm(shadow, 'distance', 10)), 'shadow_color': _bgr_hex(_prm(shadow, 'color', 0))})
    else:
        return None
    keys = {}
    tk = _map(trim, 'end')
    if tk: keys['trim'] = [[round(s + t, 3), round(v / 100.0, 4), 'linear'] for t, v in tk]
    elif trim is not None and _prm(trim, 'end', 100) < 100: L['trim'] = _prm(trim, 'end') / 100.0
    if tr is not None:
        sk = _map(tr, 'Scale_x')
        if sk: keys['scale'] = [[round(s + t, 3), round(v / 100.0, 4), 'linear'] for t, v in sk]
        elif _prm(tr, 'Scale_x', 100) != 100: L['scale'] = _prm(tr, 'Scale_x') / 100.0
        rk = _map(tr, 'Rotation')
        if rk: keys['rot'] = [[round(s + t, 3), round(v, 3), 'linear'] for t, v in rk]
        elif _prm(tr, 'Rotation', 0): L['rot'] = float(_prm(tr, 'Rotation'))
        px, py = _prm(tr, 'Position_x', 0.5), _prm(tr, 'Position_y', 0.5)
        if abs(px - 0.5) > 1e-4: L['x'] = round(W / 2 + (px - 0.5) * W, 1)
        if abs(py - 0.5) > 1e-4: L['y'] = round(H / 2 + (py - 0.5) * H, 1)
        L['pivot'] = [W / 2, H / 2]        # Filmora turns a pen layer around the canvas centre
    try:
        ok = _kf(json.loads(c['pipBuf']).get('OpacityKeyFrame', ''))
    except Exception: ok = []
    if ok: keys['opacity'] = [[round(s + t / U, 3), round(v / 100.0, 3), 'linear'] for t, v in ok]
    if keys: L['keys'] = keys
    return L


def native_layer(L):
    """spec pen layer -> native_wfp scene layer (type 'pen')"""
    return dict(L)


def pen_to_clip(proto, L, regen, frame, set_param, find_fx, transform, pipbuf):
    """fill a cloned Filmora pen clip with the spec layer L (helpers come from native_wfp to avoid a circular import)"""
    import copy
    W, H = 1920.0, 1080.0
    c = copy.deepcopy(proto); regen(c)
    s, e = frame(L['start']), frame(L['end'])
    c['tlBegin'], c['tlEnd'], c['inPoint'], c['outPoint'] = s, e, 0, e - s
    anc = anchors(L['path'], bool(L.get('norm')), (W, H))
    path = next(x for ch in c['effectChainList'] for x in ch['effectList'] if x['display'] == 'path')
    cm = json.loads(path['effectMask']['custom_mask'])
    p0 = cm['paths'][0]
    tmpl = p0['points'][0]
    empty_kf = '{"Version": 3,"ParameterType": 0,"keyframeSets": [],"MD5":"d41d8cd98f00b204e9800998ecf8427e"}'
    def ctrl(kind, xy):
        return {'type': kind, 'value_x': xy[0] / W, 'value_y': xy[1] / H, 'keyframe_x': empty_kf, 'keyframe_y': empty_kf}
    pts = []
    for p, l, r in anc:
        q = {'type': 0, 'value_x': p[0] / W, 'value_y': p[1] / H, 'keyframe_x': empty_kf, 'keyframe_y': empty_kf}
        if l or r:
            q['left_ctrl_point'] = ctrl(1, l or p); q['right_ctrl_point'] = ctrl(2, r or p)
        pts.append(q)
    p0['points'] = pts; p0['is_closed'] = bool(L.get('closed', False))
    path['effectMask']['custom_mask'] = json.dumps(cm, separators=(',', ': ')).replace('": ', '": ')
    from . import native_wfp as N
    stroke = find_fx(c, 'graphic/effect/path_stroke'); fill = find_fx(c, 'graphic/effect/path_fill'); trim = find_fx(c, 'graphic/effect/path_trim')
    shadow = find_fx(c, 'graphic/effect/path_dropshadow')
    wid = float(L.get('width', 8 if L.get('color') else 0))
    set_param(stroke, 'color', N.bgr(L.get('color', '#FFFFFF'))); set_param(stroke, 'lineSize', int(round(wid)))
    set_param(stroke, 'alpha', int(round(100 * float(L.get('stroke_opacity', 1.0) if wid else 0))))
    has_fill = L.get('fill') is not None
    set_param(fill, 'colorStart', N.bgr(L['fill']) if has_fill else 0); set_param(fill, 'alpha', int(round(100 * float(L.get('fill_opacity', 1.0)))) if has_fill else 0)
    set_param(fill, 'fillType', 1)
    set_param(fill, 'colorEnd', N.bgr(L['fill2'] if L.get('fill2') is not None else (L.get('fill') or '#000000')))
    set_param(fill, 'blur', float(L.get('fill_blur', 0)))
    sh = float(L.get('shadow', 0))
    set_param(shadow, 'alpha', int(round(sh * 100))); set_param(shadow, 'blur', int(L.get('shadow_blur', 27))); set_param(shadow, 'distance', int(L.get('shadow_dy', 8)))
    set_param(shadow, 'color', N.bgr(L.get('shadow_color', '#000000')))
    keys = L.get('keys') or {}
    tk = keys.get('trim')
    if tk:
        trim['paramMapList'] = [{'key': 3, 'keyFrame': {'parameter': N.kf([(t - L['start'], v * 100.0) for t, v in tk])}, 'name': 'end'}]
        set_param(trim, 'end', tk[0][1] * 100.0)
    else:
        trim['paramMapList'] = []; set_param(trim, 'end', 100.0 * float(L.get('trim', 1.0)))
    ck = {}
    if keys.get('scale'): ck['sx'] = ck['sy'] = [(t, v * 100.0) for t, v in keys['scale']]
    if keys.get('rot'): ck['rot'] = [(t, v) for t, v in keys['rot']]
    transform(c, ck, L['start'], {'x': W / 2, 'y': H / 2, 'sx': 100.0 * float(L.get('scale', 1.0)), 'sy': 100.0 * float(L.get('scale', 1.0)), 'rot': float(L.get('rot', 0.0))})
    pipbuf(c, [(t, v * 100.0) for t, v in keys['opacity']] if keys.get('opacity') else None, L['start'])
    return c


def demo_scene():
    """tiny demonstration: a heart that draws itself and a glowing underline"""
    heart = [[960, 420, 960, 420, 960, 420], [1080, 330, 1020, 330, 1130, 330], [1110, 450, 1110, 400, 1110, 500], [960, 640, 1040, 580, 880, 580],
             [810, 450, 810, 500, 810, 400], [840, 330, 790, 330, 900, 330]]
    return {'duration': 4.0, 'layers': [
        {'type': 'pen', 'path': heart, 'closed': True, 'color': '#FFFFFF', 'width': 8, 'fill': '#FF3B6B', 'fill_opacity': 0.9, 'start': 0.3, 'end': 4.0,
         'keys': {'trim': [[0.3, 0.0], [1.6, 1.0]]}}]}
