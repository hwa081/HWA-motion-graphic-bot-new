"""Native Filmora .wfp builder: shapes (pen / rectangle) and text as real editable layers, no video import.

Method (from the wfp guide): NEVER build from nothing. Clone a real Filmora project (mgl/templates/native_sample.wfp),
keep every structure exactly as Filmora wrote it and only change values: times, colours, positions, text, keyframes.

Scene = {"duration": 5.0, "layers": [ ... ]}   (layers are bottom -> top)
  {"type": "rect", "x": 960, "y": 540, "w": 1920, "h": 1080, "color": "#0B1020", "start": 0, "end": 5,
   "keys": {"x": [(t, px)], "y": [(t, px)], "sx": [(t, percent)], "sy": [(t, percent)], "rot": [(t, deg)], "opacity": [(t, 0..100)]}}
  {"type": "text", "text": "HELLO", "x": 960, "y": 540, "size": 72, "color": "#FFFFFF", "start": 0.5, "end": 5, "keys": {...}}
Key times t are seconds from the scene start. Positions are pixels on a 1920x1080 frame (centre of the layer).
UNVERIFIED: not opened in Filmora by the bot itself - the user must confirm. Keyframes are written without tangents (checksum formula verified).
"""
import copy, hashlib, json, os, re, struct, time, uuid, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, 'templates', 'native_sample.wfp')
PEN_SAMPLE = os.path.join(HERE, 'templates', 'pen_sample.wfp')     # made in Filmora by the user: two free pen shapes with fill / stroke / shadows / trim / keyframes
W, H, FPS, U = 1920.0, 1080.0, 25, 10000000


def _g():
    return str(uuid.uuid4())


def _G():
    a = str(uuid.uuid4()).upper().split('-')
    return '{%s-%s-%s-%s-%s}' % (a[0], a[1], a[2].lower(), a[3], a[4])


def bgr(color):
    if isinstance(color, int): return color
    c = color.lstrip('#'); r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return (b << 16) | (g << 8) | r


def kf(points):
    """Filmora keyframe string without tangents; MD5 = md5 of little-endian float64 triples (time, 1.0, value)."""
    pts = [(float(t), float(v)) for t, v in sorted(points)]
    md5 = hashlib.md5(b''.join(struct.pack('<ddd', t, 1.0, v) for t, v in pts)).hexdigest()
    body = ','.join('{"_time": %s,"Interpolation": 1,"_value": %s}' % (repr(t), repr(v)) for t, v in pts)
    return '{"Version": 3,"ParameterType": 0,"keyframeSets": [%s],"MD5":"%s"}' % (body, md5)


def _ud_get(o, key):
    for u in o['userData']:
        if u['key'] == key: return u
    return None


def _ud_text(o, key, text, pad=64):
    u = _ud_get(o, key)
    raw = text.encode('utf-8'); raw = raw + b'\0' * (pad - len(raw)) if pad else raw
    import base64
    u['data'] = base64.b64encode(raw).decode('ascii'); u['size'] = len(raw)


def _regen_ids(node):
    """fresh thisUId for every clip / effect, fresh uuid inside custom masks"""
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k == 'thisUId': node[k] = _g()
            elif isinstance(v, str) and '"uuid"' in v: node[k] = re.sub(r'"uuid": "[0-9a-f-]{36}"', lambda _: '"uuid": "%s"' % _g(), v)
            else: _regen_ids(v)
    elif isinstance(node, list):
        for x in node: _regen_ids(x)


def _find_fx(clip, fid):
    for ch in clip['effectChainList']:
        for e in ch['effectList']:
            if e['id'] == fid: return e
    return None


def _set_param(e, name, value):
    for p in e['paramList']:
        if p['name'] == name:
            p['fxParam']['unValue'] = value; return
    e['paramList'].append({'fxParam': {'paramType': 3, 'unValue': value}, 'name': name})


def _pipbuf(clip, op_keys, rel0):
    pb = json.loads(clip['pipBuf'])
    if op_keys:
        pts = [((t - rel0) * U, v) for t, v in op_keys]
        pb['OpacityKeyFrame'] = kf(pts); pb['Opacity'] = float(pts[0][1])
    else:
        pb['OpacityKeyFrame'] = kf([]) if False else '{"Version": 3,"ParameterType": 0,"keyframeSets": [],"MD5":"d41d8cd98f00b204e9800998ecf8427e"}'
        pb['Opacity'] = 100.0
    s = json.dumps(pb, separators=(',', ':'))
    clip['pipBuf'] = s; clip['pipBufSize'] = len(s.encode('utf-8')) + 1


def _transform(clip, keys, start, base):
    """keys: x,y px; sx,sy percent; rot deg. base: static fallbacks."""
    e = _find_fx(clip, 'video/effect/transform')
    maps = []
    def static(name, v): _set_param(e, name, float(v))
    spec = {'Position_x': ('x', lambda v: v / W), 'Position_y': ('y', lambda v: v / H), 'Scale_x': ('sx', lambda v: v), 'Scale_y': ('sy', lambda v: v), 'Rotation': ('rot', lambda v: v)}
    for name, (k, conv) in spec.items():
        pts = keys.get(k)
        if pts:
            rel = [(t - start, conv(v)) for t, v in pts]
            static(name, rel[0][1])
            if len(rel) > 1: maps.append({'key': 3, 'keyFrame': {'parameter': kf(rel)}, 'name': name})
        else:
            static(name, conv(base[k]))
    e['paramMapList'] = maps


def _frame(t):
    return int(round(t * FPS)) * (U // FPS)


def _rect_clip(proto, L):
    c = copy.deepcopy(proto); _regen_ids(c)
    s, e = _frame(L['start']), _frame(L['end'])
    c['tlBegin'], c['tlEnd'], c['inPoint'], c['outPoint'] = s, e, 0, e - s
    w, h = L['w'] / W, L['h'] / H
    r = _find_fx(c, 'graphic/effect/path_graphic_rect')
    for n, v in (('start_x', 0.5 - w / 2), ('start_y', 0.5 - h / 2), ('width', w), ('height', h)): _set_param(r, n, v)
    for fx in ('graphic/effect/path_fill',):
        _find_fx(c, fx)['paramList'][0]['fxParam']['unValue'] = bgr(L.get('color', '#FFFFFF'))
    keys = L.get('keys', {})
    _transform(c, keys, L['start'], {'x': L['x'], 'y': L['y'], 'sx': 100.0, 'sy': 100.0, 'rot': 0.0})
    _pipbuf(c, keys.get('opacity'), L['start'])
    return c


def _spec_pen_layer(L, st, en, keys):
    """spec / pen.py layer {path, closed, color, width, fill, fill_opacity, draw} -> my native pen layer (points, fill, stroke, trim keys); None if unusable"""
    pts = []
    for a_ in L.get('path') or []:
        a_ = list(a_)
        pts.append((a_[0], a_[1], (a_[2], a_[3]), (a_[4], a_[5])) if len(a_) >= 6 else (a_[0], a_[1]))
    if len(pts) < 2: return None
    keys = dict(keys or {})
    lay = {'type': 'pen', 'points': pts, 'closed': bool(L.get('closed', True)), 'norm': bool(L.get('norm')), 'start': st, 'end': en, 'keys': keys}
    if L.get('fill'): lay.update(fill=_hex(L['fill']), fill_alpha=int(100 * float(L.get('fill_opacity', 1.0))))
    if L.get('color') or not L.get('fill'): lay.update(stroke=_hex(L.get('color', 'white')), stroke_w=int(float(L.get('width', 6))))
    raw = L.get('keys') if isinstance(L.get('keys'), dict) else {}
    if raw.get('trim') and 'trim_end' not in keys: keys['trim_end'] = [(float(t), float(v) * 100.0) for t, v in raw['trim']]
    if raw.get('scale') and 'sx' not in keys: keys['sx'] = keys['sy'] = [(float(t), float(v) * 100.0) for t, v in raw['scale']]
    if raw.get('rot') and 'rot' not in keys: keys['rot'] = [(float(t), float(v)) for t, v in raw['rot']]
    if raw.get('opacity') and 'opacity' not in keys: keys['opacity'] = [(float(t), float(v) * 100.0) for t, v in raw['opacity']]
    if float(L.get('shadow', 0) or 0) > 0: lay.update(shadow='#000000', shadow_dist=int(L.get('shadow_dy', 8)), shadow_blur=int(L.get('shadow_blur', 27)), shadow_alpha=int(100 * min(1.0, float(L['shadow']))))
    if L.get('fill'): lay['fill2'] = _hex(L['fill2']) if L.get('fill2') else lay['fill']
    if L.get('fill_blur') is not None: lay['fill_blur'] = int(L['fill_blur'])
    dr = L.get('draw') if isinstance(L.get('draw'), dict) else None
    if dr and 'trim_end' not in keys: keys['trim_end'] = [(st, 0.0), (min(en, st + max(0.2, float(dr.get('dur', 1.0)))), 100.0)]
    return lay


def _pen_points(L):
    """layer points -> list of (x, y, left, right) normalized 0..1 of the frame (px by default, or {'norm': True}).
    A point is (x, y) = corner, or (x, y, left, right) with Bezier handles (left = incoming, right = outgoing, either may be None)."""
    def n(p):
        return None if p is None else ((p[0], p[1]) if L.get('norm') else (p[0] / W, p[1] / H))
    out = []
    for p in L['points']:
        a = n(p[:2]); l = n(p[2]) if len(p) > 2 else None; r = n(p[3]) if len(p) > 3 else None
        out.append((a[0], a[1], l, r))
    return out


def _centroid(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)



def _empty_kf():
    return '{"Version": 3,"ParameterType": 0,"keyframeSets": [],"MD5":"d41d8cd98f00b204e9800998ecf8427e"}'


def _pen_clip(proto, L):
    """Free pen shape (straight-segment polygon / polyline) = a real editable Filmora pen layer.
    Layer keys: points [(x,y)px], closed, fill/fill2/fill_alpha/fill_blur, stroke/stroke_w/stroke_alpha/stroke_blur,
    shadow/shadow_dist/shadow_blur/shadow_alpha, keys: x,y (px, centre of the shape), sx, sy, rot, opacity, trim_start, trim_end (0..100)."""
    c = copy.deepcopy(proto); _regen_ids(c)
    s, e = _frame(L['start']), _frame(L['end'])
    c['tlBegin'], c['tlEnd'], c['inPoint'], c['outPoint'] = s, e, 0, e - s
    pts = _pen_points(L); cx, cy = _centroid(pts)
    # 1) the path itself
    pe = _find_fx(c, 'graphic/effect/path')
    mask = json.loads(pe['effectMask']['custom_mask'])
    P = mask['paths'][0]; tpl = copy.deepcopy(P['points'][0])
    P['points'] = []
    for x, y, lh, rh in pts:
        q = copy.deepcopy(tpl)
        for k in ('left_ctrl_point', 'right_ctrl_point'): q.pop(k, None)
        q['type'] = 0; q['value_x'] = round(x, 8); q['value_y'] = round(y, 8)
        q['keyframe_x'] = q['keyframe_y'] = _empty_kf()
        for key, typ, h in (('left_ctrl_point', 1, lh), ('right_ctrl_point', 2, rh)):
            if h is not None:
                q[key] = {'type': typ, 'value_x': round(h[0], 8), 'value_y': round(h[1], 8), 'keyframe_x': _empty_kf(), 'keyframe_y': _empty_kf()}
        P['points'].append(q)
    P['is_closed'] = bool(L.get('closed', True))
    pe['effectMask']['custom_mask'] = json.dumps(mask, separators=(',', ': '), ensure_ascii=False)
    # 2) fill
    f = _find_fx(c, 'graphic/effect/path_fill')
    if L.get('fill'):
        _set_param(f, 'colorStart', bgr(L['fill']))
        if L.get('fill2'): _set_param(f, 'colorEnd', bgr(L['fill2']))
        else: f['paramList'] = [p for p in f['paramList'] if p['name'] != 'colorEnd']
        _set_param(f, 'alpha', int(L.get('fill_alpha', 100)))
    else:
        _set_param(f, 'alpha', 0)
    _set_param(f, 'blur', float(L.get('fill_blur', 0)))
    # 3) stroke
    st = _find_fx(c, 'graphic/effect/path_stroke')
    if L.get('stroke'):
        _set_param(st, 'color', bgr(L['stroke'])); _set_param(st, 'lineSize', int(L.get('stroke_w', 4)))
        _set_param(st, 'alpha', int(L.get('stroke_alpha', 100))); _set_param(st, 'blur', float(L.get('stroke_blur', 0)))
    else:
        _set_param(st, 'lineSize', 0); _set_param(st, 'alpha', 0)
    # 4) shadows (inner shadow is switched off and its keyframes dropped)
    ins = _find_fx(c, 'graphic/effect/path_innershadow')
    if ins is not None:
        ins['paramMapList'] = []
        if 'paramList' in ins: _set_param(ins, 'alpha', 0)
    ds = _find_fx(c, 'graphic/effect/path_dropshadow')
    if ds is not None:
        if L.get('shadow'):
            _set_param(ds, 'color', bgr(L['shadow'])); _set_param(ds, 'distance', int(L.get('shadow_dist', 8)))
            _set_param(ds, 'blur', int(L.get('shadow_blur', 20))); _set_param(ds, 'alpha', int(L.get('shadow_alpha', 40)))
        else:
            _set_param(ds, 'alpha', 0)
    # 5) trim (draw-on animation): 0..100 percent of the path length
    tr = _find_fx(c, 'graphic/effect/path_trim')
    keys = L.get('keys', {})
    maps = []
    for name, k, default in (('start', 'trim_start', 0.0), ('end', 'trim_end', 100.0)):
        pk = keys.get(k)
        if pk:
            rel = [(t - L['start'], float(v)) for t, v in pk]
            _set_param(tr, name, rel[0][1])
            if len(rel) > 1: maps.append({'key': 3, 'keyFrame': {'parameter': kf(rel)}, 'name': name})
        else:
            _set_param(tr, name, default)
    _set_param(tr, 'offset', 0.0)
    tr['paramMapList'] = maps
    # 6) transform: Position is an OFFSET from where the path is drawn (0.5 = not moved); x,y keys are the wanted shape centre
    t = dict(keys)
    for k, c0 in (('x', cx * W), ('y', cy * H)):
        if k in t: t[k] = [(tt, 960.0 + (v - c0) if k == 'x' else 540.0 + (v - c0)) for tt, v in t[k]]
    _transform(c, t, L['start'], {'x': 960.0, 'y': 540.0, 'sx': 100.0, 'sy': 100.0, 'rot': 0.0})
    _pipbuf(c, keys.get('opacity'), L['start'])
    return c


def ngon(cx, cy, r, n=48, rot=0.0, r2=None):
    """points of a regular polygon / circle (n large) / star (r2 = inner radius, n = number of tips)"""
    import math
    pts = []
    if r2 is None:
        for i in range(n): a = rot + 2 * math.pi * i / n; pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    else:
        for i in range(2 * n):
            a = rot + math.pi * i / n; rr = r if i % 2 == 0 else r2; pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def circle(cx, cy, r):
    """a true round circle: 4 Bezier points (handles k = 0.5523 r)"""
    k = 0.5522847498 * r
    return [(cx, cy - r, (cx - k, cy - r), (cx + k, cy - r)), (cx + r, cy, (cx + r, cy - k), (cx + r, cy + k)),
            (cx, cy + r, (cx + k, cy + r), (cx - k, cy + r)), (cx - r, cy, (cx - r, cy + k), (cx - r, cy - k))]


def smooth(points, closed=True, tension=1.0):
    """smooth curve through the given (x, y) points (Catmull-Rom -> Bezier handles). Use for blobs, waves, rounded lines."""
    n = len(points); out = []
    for i, (x, y) in enumerate(points):
        if not closed and i == 0: p0, p2 = points[0], points[1]
        elif not closed and i == n - 1: p0, p2 = points[-2], points[-1]
        else: p0, p2 = points[(i - 1) % n], points[(i + 1) % n]
        dx, dy = (p2[0] - p0[0]) / 6.0 * tension, (p2[1] - p0[1]) / 6.0 * tension
        left = None if (not closed and i == 0) else (x - dx, y - dy)
        right = None if (not closed and i == n - 1) else (x + dx, y + dy)
        out.append((x, y, left, right))
    return out


TEXT_SCALE = 2.323103          # read from a real Filmora project: text is drawn at FontSize x TextScale pixels


def text_width(text, px):
    """width in pixels of one line of bold text at `px` (Poppins metrics, x0.92 because Filmora's Arial is a little narrower)"""
    try:
        from mgl import engine as E
        return E.text_w(str(text), E.font_path('bold_italic'), px) * 0.92
    except Exception:
        return 0.58 * px * len(str(text))


def text_layers(text, x, y, size, color, st, en, keys=None, anchor='c', maxw=1840.0, line_h=1.18):
    """one or more native text layers: lines are split (Filmora text is one line per layer), every line is shrunk to fit `maxw`, anchor l / r is turned into the centre Filmora wants"""
    lines = [ln for ln in str(text).replace('\r', '').split('\n')] or ['']
    lines = [ln for ln in lines if ln.strip()] or ['']
    out = []; n = len(lines); keys = keys or {}
    for i, ln in enumerate(lines):
        px = float(size); w = text_width(ln, px)
        if w > maxw: px *= maxw / w; w = maxw
        dy = (i - (n - 1) / 2.0) * float(size) * line_h
        dx = {'l': w / 2.0, 'r': -w / 2.0}.get(anchor, 0.0)
        k = {kk: ([(t, v + dx) for t, v in vv] if kk == 'x' else [(t, v + dy) for t, v in vv] if kk == 'y' else vv) for kk, vv in keys.items()}
        out.append({'type': 'text', 'text': ln, 'x': x + dx, 'y': y + dy, 'size': px, 'color': color, 'start': st, 'end': en, 'keys': k})
    return out


def _text_clip(proto_main, proto_nested, L, new_tid):
    m = copy.deepcopy(proto_main); n = copy.deepcopy(proto_nested)
    _regen_ids(m); _regen_ids(n)
    s, e = _frame(L['start']), _frame(L['end']); ln = e - s
    m['tlBegin'], m['tlEnd'], m['inPoint'], m['outPoint'], m['timelineId'] = s, e, 0, ln, new_tid
    n['timelineId'] = new_tid
    # fresh GUIDs so no two objects share an id
    clip_guid = _G(); _ud_text(m, 3, clip_guid)
    u55 = _ud_get(m, 55); j = json.loads(u55['data'] and __import__('base64').b64decode(u55['data']).rstrip(b'\0').decode('utf-8'))
    j['Key_AncestralGuid'] = _G().lower(); j['Key_TimelineGuid'] = _G().lower()
    raw = json.dumps(j, separators=(',', ':'), ensure_ascii=False).encode('utf-8') + b'\0'
    u55['data'] = __import__('base64').b64encode(raw).decode('ascii'); u55['size'] = len(raw)
    _ud_text(n, 11000, _G()); _ud_text(n, 3, _G())
    nc = n['trackInfos'][0]['clipList'][0]
    nc['tlBegin'], nc['tlEnd'], nc['inPoint'], nc['outPoint'] = 0, ln, 0, ln
    n['trackInfos'][0]['uuid'] = _g()
    _ud_text(nc, 3, _G())
    sb = json.loads(nc['scriptBuf']); sb['Text'] = L['text']
    for td in sb['TextData']:
        td['CharData'] = L['text']
        if 'size' in L:
            fs = float(L['size']) / float(sb.get('TextScale', TEXT_SCALE) or TEXT_SCALE)          # Filmora draws FontSize x TextScale pixels
            for k in ('FontSize', 'FontHSize', 'FontVSize'): td['Basic'][k] = fs
            sb['ScaleX'] = min(1.0, (text_width(L['text'], float(L['size'])) + 0.5 * float(L['size'])) / W)       # the text box (fraction of the frame)
            sb['ScaleY'] = min(1.0, 1.35 * float(L['size']) / H)
        td['Basic']['TextColor'] = [{'Color': bgr(L.get('color', '#FFFFFF'))}]
    s2 = json.dumps(sb, separators=(',', ':'), ensure_ascii=False)
    nc['scriptBuf'] = s2; nc['scriptBufSize'] = len(s2.encode('utf-8')) + 1
    # static transform inside the nested timeline (no leftover animation of the sample)
    te = _find_fx(nc, 'video/effect/transform')
    if te is not None: te['paramMapList'] = []
    keys = L.get('keys', {})
    _transform(m, keys, L['start'], {'x': L['x'], 'y': L['y'], 'sx': 100.0, 'sy': 100.0, 'rot': 0.0})
    _pipbuf(m, keys.get('opacity'), L['start'])
    return m, n, clip_guid


def build(out_path, name, scene, sample=SAMPLE, sync_duration=True):
    z = zipfile.ZipFile(sample)
    names = [i.filename for i in z.infolist()]
    wes_n = next(x for x in names if x.endswith('timeline.wesproj')); ex_n = next(x for x in names if x.endswith('extra.json'))
    wes = json.loads(z.read(wes_n).decode('utf-8')); extra = json.loads(z.read(ex_n).decode('utf-8'))
    tls = {t['timelineId']: t for t in wes['timelineInfos']}
    main = tls[wes['currentTimelineId']]; tr = main['trackInfos']
    shapes = [c for t in tr for c in t['clipList'] if c['type'] == 26]
    proto_rect = next(c for c in shapes if (_find_fx(c, 'graphic/effect/path_graphic_rect') or {}).get('paramList') and
                      [p for p in _find_fx(c, 'graphic/effect/path_graphic_rect')['paramList'] if p['name'] == 'width'][0]['fxParam']['unValue'] < 0.02)
    texts = [c for t in tr for c in t['clipList'] if c['type'] == 7]
    proto_text, proto_nested = texts[0], copy.deepcopy(tls[texts[0]['timelineId']])
    a_proto, v_proto = tr[3], tr[4]
    proto_pen = None
    if any(L['type'] == 'pen' for L in scene['layers']):
        pz = zipfile.ZipFile(PEN_SAMPLE)
        pw = json.loads(pz.read(next(x for x in pz.namelist() if x.endswith('timeline.wesproj'))).decode('utf-8'))
        pm = next(t for t in pw['timelineInfos'] if t['timelineId'] == pw['currentTimelineId'])
        proto_pen = next(c for t in pm['trackInfos'] for c in t['clipList'] if c['type'] == 26 and _find_fx(c, 'graphic/effect/path'))
    new_tracks = [copy.deepcopy(tr[0]), copy.deepcopy(tr[1])]
    nested, mapping, nid = [], {}, 6
    for L in scene['layers']:
        if L['type'] == 'text':
            clip, nt, g = _text_clip(proto_text, proto_nested, L, nid); nested.append(nt); mapping[g] = 'Basic_1'; nid += 1
        elif L['type'] == 'rect':
            clip = _rect_clip(proto_rect, L)
        elif L['type'] == 'pen':
            if 'points' not in L and 'path' in L:           # a spec pen layer given straight to build()
                L = _spec_pen_layer(L, float(L.get('start', 0)), float(L.get('end', scene.get('duration', 8))), L.get('keys') or {}) or L
            clip = _pen_clip(proto_pen, L)
        else:
            raise ValueError('unknown layer type %s' % L['type'])
        a = copy.deepcopy(a_proto); v = copy.deepcopy(v_proto)
        a['uuid'], v['uuid'] = _g(), _g()
        v['trackTag'] = len(new_tracks); a['trackTag'] = len(new_tracks) + 1     # like the sample: video track at an even index, its empty audio track right after
        v['clipList'] = [clip]; a['clipList'] = []
        new_tracks += [v, a]
    main['trackInfos'] = new_tracks
    wes['timelineInfos'] = [main] + nested
    wes['serialNumber'] = wes.get('serialNumber', 300) + len(scene['layers'])
    extra['mediaClipsMapInfo'] = {g: {'mediaId': m, 'subClips': {}} for g, m in mapping.items()}
    extra['allMarkersInfo'] = {'beatDetectInfo': {g: {'algorithmType': 0, 'level': 0} for g in mapping}}
    dur = _frame(scene['duration'])
    zi = []
    for i in z.infolist():
        d = z.read(i.filename)
        if i.filename == wes_n: d = json.dumps(wes, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        elif i.filename == ex_n: d = json.dumps(extra, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        elif i.filename.endswith('project_info.json'):
            # SAFE METADATA: only what was tested to open in Filmora (name + save path). Dates, guid, source stay as in the sample.
            pi = json.loads(d.decode('utf-8'))
            pi['project_file_name'] = name
            pi['proj_zip_save_path'] = 'C:/Users/Public/Documents/%s.wfp' % name
            if sync_duration: pi['project_timeline_duration'] = dur
            d = json.dumps(pi, indent=4, ensure_ascii=False).encode('utf-8')
        elif i.filename.endswith('medias_info.json'):
            mi = json.loads(d.decode('utf-8'))
            for it in mi['media_items'].values():
                it['name'] = name
                if sync_duration: it['duration'] = dur
            d = json.dumps(mi, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        zi.append((i, d))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as o:
        for i, d in zi:
            ni = zipfile.ZipInfo(i.filename, date_time=time.localtime()[:6]); ni.compress_type = zipfile.ZIP_DEFLATED
            ni.create_system = 3; ni.external_attr = i.external_attr
            o.writestr(ni, d)
    return validate(out_path)


def validate(path):
    """structure checks from the guide: zip ok, JSON parses, unique thisUId, size fields, nested timelines exist, no overlap"""
    problems = []
    z = zipfile.ZipFile(path)
    if z.testzip(): problems.append('zip damaged')
    wes = json.loads(z.read(next(x for x in z.namelist() if x.endswith('timeline.wesproj'))).decode('utf-8'))
    ids, tlids = [], {t['timelineId'] for t in wes['timelineInfos']}
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == 'thisUId': ids.append(v)
                else: walk(v)
        elif isinstance(o, list):
            for x in o: walk(x)
    walk(wes)
    if len(ids) != len(set(ids)): problems.append('duplicate thisUId')
    clips = 0
    for t in wes['timelineInfos']:
        for tr in t['trackInfos']:
            last = -1
            for c in sorted(tr['clipList'], key=lambda c: c['tlBegin']):
                clips += 1
                if c['tlBegin'] < last: problems.append('overlap on a track')
                last = c['tlEnd']
                if 'pipBuf' in c and c.get('pipBufSize') != len(c['pipBuf'].encode('utf-8')) + 1: problems.append('pipBufSize')
                if 'scriptBuf' in c and c.get('scriptBufSize') != len(c['scriptBuf'].encode('utf-8')) + 1: problems.append('scriptBufSize')
                if c['type'] == 7 and c['timelineId'] not in tlids: problems.append('missing nested timeline %s' % c['timelineId'])
    return {'path': path, 'clips': clips, 'timelines': len(tlids), 'problems': sorted(set(problems))}


def demo_scene():
    """5 s intro: dark background, 3 bars sliding in, a rotating square, title + subtitle (all native editable layers)"""
    L = [{'type': 'rect', 'x': 960, 'y': 540, 'w': 1920, 'h': 1080, 'color': '#0B1020', 'start': 0, 'end': 5}]
    for i, (y, col) in enumerate(((380, '#FF6A00'), (540, '#22D3EE'), (700, '#A78BFA'))):
        t0 = 0.2 + i * 0.2
        L.append({'type': 'rect', 'x': 960, 'y': y, 'w': 900, 'h': 24, 'color': col, 'start': t0, 'end': 5,
                  'keys': {'x': [(t0, 100), (t0 + 0.7, 960)], 'opacity': [(t0, 0), (t0 + 0.3, 100)]}})
    L.append({'type': 'rect', 'x': 1500, 'y': 540, 'w': 220, 'h': 220, 'color': '#FF6A00', 'start': 0.4, 'end': 5,
              'keys': {'sx': [(0.4, 10), (1.4, 100)], 'sy': [(0.4, 10), (1.4, 100)], 'rot': [(0.4, 0), (1.4, 180)], 'opacity': [(0.4, 0), (0.7, 100)]}})
    L.append({'type': 'text', 'text': 'MOTION BOT', 'x': 800, 'y': 520, 'size': 72, 'color': '#FFFFFF', 'start': 0.9, 'end': 5,
              'keys': {'y': [(0.9, 580), (1.5, 520)], 'opacity': [(0.9, 0), (1.5, 100)]}})
    L.append({'type': 'text', 'text': 'made natively for Filmora', 'x': 800, 'y': 620, 'size': 36, 'color': '#22D3EE', 'start': 1.4, 'end': 5,
              'keys': {'opacity': [(1.4, 0), (2.0, 100)]}})
    return {'duration': 5.0, 'layers': L}


def pen_demo_scene():
    """5 s: dark background, a star that draws itself and spins, a glowing gradient circle, a growing chart line, a blob - all free pen shapes"""
    L = [{'type': 'rect', 'x': 960, 'y': 540, 'w': 1920, 'h': 1080, 'color': '#0B1020', 'start': 0, 'end': 5}]
    L.append({'type': 'pen', 'points': ngon(480, 540, 230, n=5, rot=-1.5708, r2=100), 'fill': '#FF6A00', 'fill2': '#FFD166', 'fill_alpha': 90,
              'stroke': '#FFFFFF', 'stroke_w': 5, 'shadow': '#000000', 'shadow_dist': 10, 'shadow_blur': 30, 'shadow_alpha': 45, 'start': 0.2, 'end': 5,
              'keys': {'trim_end': [(0.2, 0), (1.2, 100)], 'rot': [(1.2, 0), (4.5, 360)], 'opacity': [(0.2, 0), (0.5, 100)]}})
    L.append({'type': 'pen', 'points': circle(1000, 540, 170), 'fill': '#22D3EE', 'fill2': '#A78BFA', 'fill_alpha': 85, 'fill_blur': 14,
              'start': 0.6, 'end': 5, 'keys': {'sx': [(0.6, 20), (1.6, 100)], 'sy': [(0.6, 20), (1.6, 100)], 'opacity': [(0.6, 0), (1.0, 100)]}})
    line = smooth([(1300, 800), (1420, 700), (1520, 760), (1640, 600), (1740, 640), (1840, 420)], closed=False)
    L.append({'type': 'pen', 'points': line, 'closed': False, 'stroke': '#34D399', 'stroke_w': 10, 'stroke_blur': 2, 'start': 1.0, 'end': 5,
              'keys': {'trim_end': [(1.0, 0), (2.6, 100)]}})
    return {'duration': 5.0, 'layers': L}


# ------------------------------------------------------------------ AI design (spec) -> native Filmora scene
NATIVE_TYPES = ('text', 'rrect', 'circle', 'line', 'blob', 'chip', 'card', 'chart', 'progress', 'icon', 'device', 'pen')
COMPOSITE = ('chip', 'card', 'chart', 'progress', 'icon', 'device')      # made of several native layers
_BG = {'light_pastel': '#F4F1FA', 'sunset': '#2B1B3D', 'ocean': '#082B45', 'neon_night': '#0A0620', 'dark_aurora': '#0B1020'}


def _hex(c, default='#FFFFFF'):
    if c is None: return default
    if isinstance(c, str):
        c = c.strip()
        if c.startswith('#') and len(c) == 7: return c.upper()
        try:
            from mgl import spec as S
            c = S.parse_color(c)
        except Exception:
            return default
    try:
        return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(float(v) * 255)))) for v in list(c)[:3])
    except Exception:
        return default


def rrect_points(cx, cy, w, h, r):
    """rounded rectangle as Bezier pen points (clockwise from the top-left corner)"""
    r = max(0.0, min(r, w / 2.0, h / 2.0)); x0, y0, x1, y1 = cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0
    if r < 1.0: return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    k = 0.5522847498 * r
    return [(x0 + r, y0), (x1 - r, y0, None, (x1 - r + k, y0)), (x1, y0 + r, (x1, y0 + r - k), None), (x1, y1 - r, None, (x1, y1 - r + k)),
            (x1 - r, y1, (x1 - r + k, y1), None), (x0 + r, y1, None, (x0 + r - k, y1)), (x0, y1 - r, (x0, y1 - r + k), None),
            (x0, y0 + r, None, (x0, y0 + r - k)), (x0 + r, y0, (x0 + r - k, y0), None)][:-1]


def _num_keys(spec_keys, name, start, end, conv=lambda v: v):
    pts = []
    for row in (spec_keys or {}).get(name) or []:
        try: t, v = float(row[0]), float(row[1])
        except (TypeError, ValueError, IndexError): continue
        pts.append((min(max(t, start), end), conv(v)))
    pts = sorted(dict(pts).items())
    return pts if pts else None


def _grow(L, st, en, dd=1.4):
    g = L.get('grow') if isinstance(L.get('grow'), dict) else {}
    a = float(g.get('start', st + 0.25)); b = a + max(float(g.get('dur', dd)), 0.2)
    return min(a, en), min(b, en)


def _final(L, name, default):
    """the number a keyed / plain value ends at"""
    ks = (L.get('keys') or {}).get(name)
    if ks:
        try: return float(ks[-1][1])
        except (TypeError, ValueError, IndexError): pass
    try: return float(L.get(name, default))
    except (TypeError, ValueError): return default


def _arc(cx, cy, r, a0, a1, step=7.0):
    import math
    n = max(2, int(abs(a1 - a0) / step) + 1)
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / (n - 1))), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / (n - 1)))) for i in range(n)]


def _pen(points, closed=True, **kw):
    d = {'type': 'pen', 'points': points, 'closed': closed}; d.update(kw); return d


def _txt(text, x, y, size, color, maxw=1500.0, **kw):
    d = {'type': 'text', 'text': str(text), 'x': x, 'y': y, 'size': size, 'color': color, 'maxw': maxw}; d.update(kw); return d


def _composite(ty, L, st, en, x, y):
    """native parts (pen shapes + text) for chip / card / chart / progress / icon / device. Parts may carry their own `keys` (growth animations)."""
    try:
        from mgl import spec as S
        pal = [_hex(c) for c in S.DEFAULT_PALETTE]
    except Exception:
        pal = ['#5B8CFF', '#34D399', '#FBBF24', '#F472B6', '#A78BFA']
    parts = []
    if ty == 'chip':
        w, h = float(L.get('w', 400)), float(L.get('h', 150)); light = float(L.get('light', 0) or 0) > 0.5
        parts.append(_pen(rrect_points(x, y, w, h, h / 2.0), fill='#FFFFFF', fill_alpha=96 if light else 14, stroke=None if light else '#FFFFFF', stroke_w=2, stroke_alpha=35,
                          shadow='#000000' if light else None, shadow_dist=8, shadow_blur=22, shadow_alpha=20))
        parts.append(_txt(L.get('label', ''), x, y, h * 0.34, '#1A1A22' if light else '#FFFFFF', maxw=w * 0.82))
    elif ty == 'card':
        sc = float(L.get('scale', 1) or 1) * 1.7; w, h = 260 * sc, 360 * sc
        parts.append(_pen(rrect_points(x, y, w, h, 26 * sc), fill='#1B1D2B', fill_alpha=96, stroke='#FFFFFF', stroke_w=2, stroke_alpha=22, shadow='#000000', shadow_dist=14, shadow_blur=30, shadow_alpha=40))
        num = int(round(_final(L, 'number', 0)))
        if L.get('title') or L.get('header'): parts.append(_txt(L.get('title') or L.get('header'), x, y - h * 0.36, h * 0.062, _hex(L.get('text_color', 'white')), maxw=w * 0.86))
        big = str(L.get('big_text', '')).replace('{n}', str(num))
        if big: parts.append(_txt(big, x, y, h * 0.16, _hex(L.get('text_color', 'white')), maxw=w * 0.86))
        sub = L.get('subtitle') or L.get('body')
        if sub: parts.append(_txt(sub, x, y + h * 0.30, h * 0.05, '#C9CCE0', maxw=w * 0.86))
    elif ty == 'chart':
        w, h = float(L.get('w', 600)), float(L.get('h', 360)); data = [float(v) for v in L.get('data', [])] or [1, 2]; n = len(data)
        cols = [_hex(c) for c in L.get('colors', [])] or pal; tc = _hex(L.get('text_color', 'white')); a, b = _grow(L, st, en)
        top, base, left = y - h / 2.0, y + h / 2.0, x - w / 2.0; kind = L.get('kind', 'bar')
        if kind in ('bar', 'line'):
            parts.append(_pen([(left, base), (left + w, base)], False, stroke='#FFFFFF', stroke_w=2, stroke_alpha=25))
            mx = max(data) or 1.0; slot = w / n
            if kind == 'bar':
                bw = slot * 0.62
                for i, v in enumerate(data):
                    hh = max(6.0, (h * 0.9) * v / mx); cx = left + slot * (i + 0.5); a_i = min(en, a + i * 0.08); b_i = min(en, b + i * 0.08)
                    parts.append(_pen(rrect_points(cx, base - hh / 2.0, bw, hh, min(8.0, bw / 4.0)), fill=cols[i % len(cols)], fill_alpha=100,
                                      keys={'sy': [(a_i, 4.0), (b_i, 100.0)], 'y': [(a_i, base - hh * 0.04 / 2.0), (b_i, base - hh / 2.0)]}))
            else:
                pts = [(left + slot * (i + 0.5), base - (h * 0.88) * v / mx) for i, v in enumerate(data)]
                parts.append(_pen(smooth(pts, closed=False), False, stroke=cols[0], stroke_w=7, keys={'trim_end': [(a, 0.0), (b, 100.0)]}))
            for i, lb in enumerate(L.get('labels') or []):
                if i < n: parts.append(_txt(lb, left + slot * (i + 0.5), base + 26, 22, tc, maxw=slot * 0.92))
        else:                                                          # donut: arcs that draw themselves one after the other
            R = min(w, h) / 2.0 * 0.82; tot = sum(data) or 1.0; cum = 0.0
            for i, v in enumerate(data):
                f0, f1 = cum / tot, (cum + v) / tot; cum += v
                parts.append(_pen(smooth(_arc(x, y, R, -90 + 360 * f0, -90 + 360 * f1 - (2.0 if n > 1 else 0.0)), closed=False), False, stroke=cols[i % len(cols)], stroke_w=int(R * 0.26),
                                  keys={'trim_end': [(a + (b - a) * f0, 0.0), (a + (b - a) * f1, 100.0)]}))
            if L.get('center_text'): parts.append(_txt(L['center_text'], x, y, R * 0.34, tc, maxw=R * 1.4))
    elif ty == 'progress':
        w, h = float(L.get('w', 600)), float(L.get('h', 26)); val = max(0.0, min(1.0, _final(L, 'value', 1.0))); col = _hex(L.get('color', '#5b8cff')); trk = _hex(L.get('track', 'white'))
        a, b = _grow(L, st, en, 1.2); lab = L.get('label')
        if L.get('kind', 'bar') == 'ring':
            R = w / 2.0
            parts.append(_pen(circle(x, y, R), fill=None, stroke=trk, stroke_w=max(4, int(h)), stroke_alpha=18))
            parts.append(_pen(smooth(_arc(x, y, R, -90, -90 + 359.0 * max(val, 0.01)), closed=False), False, stroke=col, stroke_w=max(4, int(h)), keys={'trim_end': [(a, 0.0), (b, 100.0)]}))
            if isinstance(lab, str): parts.append(_txt(lab.replace('{p}', str(int(round(val * 100)))), x, y, w * 0.22, _hex(L.get('text_color', 'white')), maxw=w * 0.8))
        else:
            left = x - w / 2.0; fw = max(h, w * val)
            parts.append(_pen(rrect_points(x, y, w, h, h / 2.0), fill=trk, fill_alpha=18))
            parts.append(_pen(rrect_points(left + fw / 2.0, y, fw, h, h / 2.0), fill=col, fill_alpha=100,
                              keys={'sx': [(a, 3.0), (b, 100.0)], 'x': [(a, left + fw * 0.03 / 2.0), (b, left + fw / 2.0)]}))
            if isinstance(lab, str): parts.append(_txt(lab.replace('{p}', str(int(round(val * 100)))), x, y - h * 1.3, max(18, h * 0.9), _hex(L.get('text_color', 'white'))))
    elif ty == 'icon':
        sz = float(L.get('size', 60)); c = _hex(L.get('color', 'white')); lw = int(L.get('width', 4)); nm = L.get('name'); kw = dict(stroke=c, stroke_w=lw, fill=None)
        if nm == 'plus': parts += [_pen([(x - .3 * sz, y), (x + .3 * sz, y)], False, **kw), _pen([(x, y - .3 * sz), (x, y + .3 * sz)], False, **kw)]
        elif nm == 'cross': parts += [_pen([(x - .3 * sz, y - .3 * sz), (x + .3 * sz, y + .3 * sz)], False, **kw), _pen([(x - .3 * sz, y + .3 * sz), (x + .3 * sz, y - .3 * sz)], False, **kw)]
        elif nm == 'check': parts.append(_pen([(x - .35 * sz, y), (x - .1 * sz, y + .28 * sz), (x + .4 * sz, y - .3 * sz)], False, **kw))
        elif nm == 'arrow_up': parts += [_pen([(x, y + .35 * sz), (x, y - .35 * sz)], False, **kw), _pen([(x - .22 * sz, y - .13 * sz), (x, y - .35 * sz), (x + .22 * sz, y - .13 * sz)], False, **kw)]
        elif nm == 'star': parts.append(_pen(ngon(x, y, sz * .5, n=5, rot=-1.5708, r2=sz * .21), True, **kw))
        elif nm == 'send': parts += [_pen(circle(x, y, sz * .5), True, **kw), _pen([(x, y + .2 * sz), (x, y - .2 * sz)], False, **kw), _pen([(x - .13 * sz, y - .07 * sz), (x, y - .2 * sz), (x + .13 * sz, y - .07 * sz)], False, **kw)]
        elif nm == 'mic':
            parts += [_pen(rrect_points(x, y - .12 * sz, .3 * sz, .5 * sz, .15 * sz), True, **kw), _pen(smooth(_arc(x, y - .02 * sz, .26 * sz, 0, 180), closed=False), False, **kw), _pen([(x, y + .24 * sz), (x, y + .38 * sz)], False, **kw)]
    elif ty == 'device':
        w = float(L.get('w', 400)); kind = L.get('kind', 'phone'); body = _hex(L.get('body', '#121217')); scr = _hex(L.get('screen_color', '#2a2e40'))
        if kind == 'phone':
            h = w * 2.05; bz = w * 0.04
            parts += [_pen(rrect_points(x, y, w, h, w * .15), fill=body, stroke='#FFFFFF', stroke_w=2, stroke_alpha=25, shadow='#000000', shadow_dist=int(w * .06), shadow_blur=int(w * .12), shadow_alpha=40),
                      _pen(rrect_points(x, y, w - 2 * bz, h - 2 * bz, w * .11), fill=scr), _pen(rrect_points(x, y - h / 2 + bz + w * .045, w * .28, w * .06, w * .03), fill='#000000')]
        elif kind == 'laptop':
            sw = w * .84; sh = sw * .625; top = y - (sh + w * .07) / 2.0
            parts += [_pen(rrect_points(x, top + sh / 2 + w * .02, sw + w * .04, sh + w * .04, w * .03), fill=body, stroke='#FFFFFF', stroke_w=2, stroke_alpha=25),
                      _pen(rrect_points(x, top + sh / 2 + w * .02, sw, sh, w * .01), fill=scr), _pen(rrect_points(x, top + sh + w * .07, w, w * .035, w * .015), fill=body, stroke='#FFFFFF', stroke_w=2, stroke_alpha=25)]
        else:
            h = w * .62
            parts += [_pen(rrect_points(x, y, w, h, w * .03), fill=body, stroke='#FFFFFF', stroke_w=2, stroke_alpha=25, shadow='#000000', shadow_dist=int(w * .04), shadow_blur=int(w * .08), shadow_alpha=35),
                      _pen(rrect_points(x, y + h * .06, w * .96, h * .86, w * .015), fill=scr)]
            for i, c in enumerate(('#FF5F57', '#FEBC2E', '#28C840')): parts.append(_pen(circle(x - w / 2 + w * .05 + i * w * .035, y - h / 2 + h * .06, w * .011), fill=c))
    return parts


def _part_centre(pt):
    if pt['type'] == 'text': return pt['x'], pt['y']
    xs = [p[0] for p in pt['points']]; ys = [p[1] for p in pt['points']]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _place(parts, keys, x, y, st, en):
    """give every part the time range and the layer's fade / move (scale and rotation of a whole group are not applied)"""
    out = []
    for pt in parts:
        pt = dict(pt); pt['start'], pt['end'] = st, en; k = {}
        cx, cy = _part_centre(pt)
        if pt['type'] == 'text':
            kk = {}
            if keys.get('opacity'): kk['opacity'] = keys['opacity']
            for nm, c0, ref in (('x', cx, x), ('y', cy, y)):
                if keys.get(nm): kk[nm] = [(t, c0 + (v - ref)) for t, v in keys[nm]]
            out += text_layers(pt['text'], pt['x'], pt['y'], pt['size'], pt['color'], st, en, kk, 'c', pt.get('maxw', 1500.0)); continue
        if keys.get('opacity'): k['opacity'] = keys['opacity']
        for nm, c0, ref in (('x', cx, x), ('y', cy, y)):
            if keys.get(nm): k[nm] = [(t, c0 + (v - ref)) for t, v in keys[nm]]
        k.update(pt.get('keys') or {})
        pt['keys'] = k; out.append(pt)
    return out


def spec_to_scene(spec):
    """Turn an AI design (spec) into a native Filmora scene: text, rounded rectangles, circles and lines become editable layers.
    Everything else (icons, emoji, images, cards, charts, devices, particles, blobs ...) is skipped. Returns (scene, report dict).
    Approximations: easing becomes linear, the animated background becomes one flat colour, fonts use the sample font."""
    dur = float(spec.get('duration', 8)); layers = []; skipped = {}; used = 0
    bg = spec.get('background'); style = bg[0].get('style') if isinstance(bg, list) and bg and isinstance(bg[0], dict) else (bg if isinstance(bg, str) else None)
    layers.append({'type': 'rect', 'x': 960, 'y': 540, 'w': 1920, 'h': 1080, 'color': _BG.get(style, '#0B1020'), 'start': 0, 'end': dur})
    for L in spec.get('layers', []):
        ty = L.get('type')
        if ty not in NATIVE_TYPES: skipped[ty] = skipped.get(ty, 0) + 1; continue
        st = max(0.0, float(L.get('start', 0))); en = min(dur, float(L.get('end', dur)))
        if en - st < 0.1: continue
        k = L.get('keys') or {}; x, y = float(L.get('x', 960)), float(L.get('y', 540))
        keys = {}
        for nm in ('x', 'y'): 
            v = _num_keys(k, nm, st, en)
            if v: keys[nm] = v
        for nm, tgt in (('scale', 'sx'), ('rot', 'rot')):
            v = _num_keys(k, nm, st, en, (lambda q: q * 100.0) if nm == 'scale' else (lambda q: q))
            if v:
                keys[tgt] = v
                if nm == 'scale': keys['sy'] = v
        op = _num_keys(k, 'opacity', st, en, lambda q: max(0.0, min(100.0, q * 100.0)))
        # entrance animation ("in") when the design did not give its own keys
        an = (L.get('in') or {}) if isinstance(L.get('in'), dict) else {}
        if an and not op:
            d_ = max(0.15, float(an.get('dur', 0.5))); keys['opacity'] = [(st, 0.0), (min(en, st + d_), 100.0)]
            a = an.get('anim', 'fade')
            if a in ('zoom', 'pop', 'scale') and 'sx' not in keys: keys['sx'] = keys['sy'] = [(st, 40.0), (min(en, st + d_), 100.0)]
            elif a in ('slide_up', 'slide', 'rise') and 'y' not in keys: keys['y'] = [(st, y + 60), (min(en, st + d_), y)]
            elif a == 'slide_down' and 'y' not in keys: keys['y'] = [(st, y - 60), (min(en, st + d_), y)]
            elif a == 'slide_left' and 'x' not in keys: keys['x'] = [(st, x + 80), (min(en, st + d_), x)]
            elif a == 'slide_right' and 'x' not in keys: keys['x'] = [(st, x - 80), (min(en, st + d_), x)]
        elif op: keys['opacity'] = op
        if ty in COMPOSITE:
            parts = _composite(ty, L, st, en, x, y)
            if not parts: skipped[ty] = skipped.get(ty, 0) + 1; continue
            layers += _place(parts, keys, x, y, st, en); used += 1; continue
        if ty == 'blob':
            import math
            r = float(L.get('r', 200)); sd = float(L.get('seed', 3)); n = 8
            pts = [(x + r * (1 + 0.14 * math.sin(sd + i * 2.1) + 0.07 * math.cos(sd * 1.7 + i * 3.3)) * math.cos(2 * math.pi * i / n), y + r * (1 + 0.14 * math.sin(sd + i * 2.1) + 0.07 * math.cos(sd * 1.7 + i * 3.3)) * math.sin(2 * math.pi * i / n)) for i in range(n)]
            lay = {'type': 'pen', 'points': smooth(pts), 'start': st, 'end': en, 'keys': keys, 'fill': _hex(L.get('color', '#8066FF')), 'fill_alpha': int(100 * float(L.get('fill_opacity', 1.0))),
                   'fill_blur': min(80, int(r * float(L.get('softness', 0.6)) * 0.3))}
            if L.get('color2'): lay['fill2'] = _hex(L['color2'])
            layers.append(lay); used += 1; continue
        if ty == 'text':
            txt = str(L.get('text', '')).replace('{n}', '')
            if not txt.strip(): continue
            layers += text_layers(txt, x, y, float(L.get('size', 80)), _hex(L.get('color')), st, en, keys, L.get('anchor', 'c'))
        elif ty == 'pen':                                    # spec pen layer (mgl/pen.py): anchors [x,y] or [x,y,lx,ly,rx,ry] -> a real Filmora pen clip
            lay = _spec_pen_layer(L, st, en, keys)
            if lay is None: skipped[ty] = skipped.get(ty, 0) + 1; continue
            layers.append(lay)
        elif ty in ('rrect', 'circle'):
            w = float(L.get('w', 2 * float(L.get('r', 50)))) if ty == 'rrect' else 2 * float(L.get('r', 50)); h = float(L.get('h', w)) if ty == 'rrect' else w
            pts = rrect_points(x, y, w, h, float(L.get('r', 0))) if ty == 'rrect' else circle(x, y, w / 2.0)
            lay = {'type': 'pen', 'points': pts, 'start': st, 'end': en, 'keys': keys, 'fill': _hex(L.get('fill', 'white')), 'fill_alpha': int(100 * float(L.get('fill_opacity', 1.0)))}
            if L.get('fill2'): lay['fill2'] = _hex(L.get('fill2'))
            if L.get('border') and float(L.get('border_w', 0)) > 0:
                lay.update(stroke=_hex(L['border']), stroke_w=int(L.get('border_w', 3)), stroke_alpha=int(100 * float(L.get('border_opacity', 0.5))))
            if float(L.get('shadow', 0) or 0) > 0: lay.update(shadow='#000000', shadow_dist=int(L.get('shadow_dy', 8)), shadow_blur=int(L.get('shadow_blur', 20)), shadow_alpha=int(100 * min(1.0, float(L['shadow']))))
            layers.append(lay)
        elif ty == 'line':
            pts = [tuple(q) for q in L.get('points', [])]
            if len(pts) < 2: continue
            lk = dict(keys)
            if an: lk.setdefault('trim_end', [(st, 0.0), (min(en, st + float(an.get('dur', 0.6))), 100.0)])      # lines draw themselves in
            layers.append({'type': 'pen', 'points': pts, 'closed': bool(L.get('closed', False)), 'stroke': _hex(L.get('color')), 'stroke_w': int(L.get('width', 4)), 'start': st, 'end': en, 'keys': lk})
        used += 1
    return {'duration': dur, 'layers': layers, 'title': spec.get('title', '')}, {'converted': used, 'skipped': skipped, 'size_ok': True}
