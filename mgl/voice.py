"""mgl.voice - make the video FOLLOW a voice-over.

The user gives the bot an audio file (the narration). The bot
  1. listens: the AI writes down what is said, sentence by sentence, with times (language, role of each sentence, key words, numbers);
     without an AI answer the pauses of the voice are used to find the scenes (so the video is still built in time with the voice);
  2. fixes the times: every scene boundary is moved into the nearest real pause (a cut never lands in the middle of a word);
  3. designs the video so that each sentence = one scene, the key words / numbers appear when they are SPOKEN;
  4. after the design: cuts and layer starts are snapped to the sentence starts, the voice is mixed into the final audio
     (normalised, the sound effects duck underneath it).
"""
import base64, json, math, os, re, subprocess, tempfile
import numpy as np
from . import gemini

AUDIO_EXT = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.opus', '.flac', '.wma')
MAX_SEC = 600.0
SR = 16000
HOP = 0.02

SYSTEM = 'You are a careful transcriber and video editor. You listen to a voice-over and split it into scenes. Answer with JSON only.'

ROLES = ('hook', 'problem', 'step', 'feature', 'stat', 'proof', 'cta', 'outro', 'other')


def is_audio(path):
    return str(path).lower().endswith(AUDIO_EXT)


def duration(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', path], capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except ValueError: raise ValueError('cannot read the audio file %s' % os.path.basename(path))


def _pcm(path, sr=SR):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True)
    if r.returncode != 0 or not r.stdout: raise ValueError('cannot decode the audio: %s' % r.stderr.decode('utf-8', 'ignore')[-200:])
    return np.frombuffer(r.stdout, dtype=np.float32)


def envelope(path):
    """loudness (dB) every 20 ms"""
    x = _pcm(path); h = int(SR * HOP); n = len(x) // h
    if n < 2: return np.full(2, -90.0)
    rms = np.sqrt(np.mean(x[:n * h].reshape(n, h) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def pauses(db, min_len=0.16):
    """quiet stretches of the voice -> [(start, end)] in seconds"""
    lo, hi = np.percentile(db, 8), np.percentile(db, 92)
    if hi - lo < 8: return []
    thr = lo + (hi - lo) * 0.28
    out, a = [], None
    for i, v in enumerate(db):
        if v < thr and a is None: a = i
        elif v >= thr and a is not None:
            if (i - a) * HOP >= min_len: out.append((a * HOP, i * HOP))
            a = None
    if a is not None and (len(db) - a) * HOP >= min_len: out.append((a * HOP, len(db) * HOP))
    return out


def snap_time(t, pz, window=0.6):
    """move t to the middle of the nearest pause (within window seconds); a time with no pause nearby stays where it is"""
    best, bd = t, window + 1e-9
    for a, b in pz:
        c = (a + b) / 2
        d = 0 if a <= t <= b else min(abs(t - a), abs(t - b))
        if d < bd: best, bd = c, d
    return best


def segments_from_pauses(dur, pz, min_seg=1.8, max_seg=9.0):
    cuts = [c for c in sorted((a + b) / 2 for a, b in pz) if 0.8 < c < dur - 0.8]
    bounds = [0.0] + cuts + [dur]
    changed = True
    while changed:                                         # merge scenes that are too short
        changed = False
        for i in range(len(bounds) - 1):
            if bounds[i + 1] - bounds[i] < min_seg and len(bounds) > 2:
                bounds.pop(i + 1 if i + 1 < len(bounds) - 1 else i); changed = True; break
    out = []
    for a, b in zip(bounds, bounds[1:]):
        k = max(1, int(math.ceil((b - a) / max_seg)))
        out += [(a + (b - a) * j / k, a + (b - a) * (j + 1) / k) for j in range(k)]
    return [{'start': round(a, 2), 'end': round(b, 2), 'text': '', 'role': 'other', 'emphasis': []} for a, b in out]


def _prepare(path):
    """small mono mp3 for the AI (a 10 minute voice-over is ~4 MB)"""
    tmp = tempfile.mkdtemp(prefix='voice_'); mp3 = os.path.join(tmp, 'v.mp3')
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '40k', mp3], capture_output=True)
    if r.returncode != 0: raise ValueError('cannot convert the audio: %s' % r.stderr.decode('utf-8', 'ignore')[-200:])
    return mp3


def _prompt(dur):
    return ('This is a voice-over of %.1f seconds that will be turned into a motion-graphics video: every SCENE of the video follows one idea of the narration.\n'
            'Listen carefully and return ONE JSON object:\n'
            '{"language": "language name", "summary": "one sentence: what the narration is about", "mood": "e.g. energetic / calm / serious / friendly",\n'
            ' "segments": [{"start": seconds, "end": seconds, "text": "exactly what is said (same language and script as spoken)", '
            '"role": "hook|problem|step|feature|stat|proof|cta|outro|other", "emphasis": ["up to 3 key words or numbers that are said strongly or matter on screen"]}]}\n'
            'Rules: segments in time order, no gaps or overlaps, first start 0, last end %.1f; one segment = one sentence or two short related sentences (2-9 seconds); '
            'times as precise as you can hear them (start = when the first word begins).' % (dur, dur))


def _clean(data, dur, pz):
    segs = []
    for s in (data.get('segments') if isinstance(data, dict) else None) or []:
        if not isinstance(s, dict): continue
        try: a, b = float(s.get('start')), float(s.get('end'))
        except (TypeError, ValueError): continue
        text = re.sub(r'\s+', ' ', str(s.get('text') or '')).strip()
        if b <= a or not text: continue
        role = str(s.get('role') or 'other').lower(); role = role if role in ROLES else 'other'
        emp = [str(w)[:30] for w in (s.get('emphasis') or []) if str(w).strip()][:3]
        segs.append({'start': a, 'end': b, 'text': text[:400], 'role': role, 'emphasis': emp})
    if not segs: raise ValueError('the AI heard no usable sentences')
    segs.sort(key=lambda s: s['start'])
    bounds = [0.0]                                          # boundaries: the start of every sentence, moved into a real pause
    for s in segs[1:]: bounds.append(min(max(snap_time(s['start'], pz), bounds[-1] + 0.5), dur - 0.5))
    bounds.append(dur)
    out = []
    for i, s in enumerate(segs):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 0.6 and out:                             # too short to be a scene: join with the previous one
            out[-1]['end'] = b; out[-1]['text'] = (out[-1]['text'] + ' ' + s['text']).strip(); out[-1]['emphasis'] = (out[-1]['emphasis'] + s['emphasis'])[:3]; continue
        out.append(dict(s, start=round(a, 2), end=round(b, 2)))
    out[0]['start'] = 0.0; out[-1]['end'] = round(dur, 2)
    return out


def analyze(ask, path, log=print):
    """-> {'duration', 'language', 'summary', 'mood', 'segments': [...], 'source': 'ai' | 'pauses', 'note'}. Never raises because of the AI: falls back to the pauses."""
    dur = duration(path)
    if dur < 2: raise ValueError('the voice-over is shorter than 2 seconds')
    if dur > MAX_SEC: raise ValueError('the voice-over is longer than %d seconds (10 minutes)' % MAX_SEC)
    try: pz = pauses(envelope(path))
    except Exception as ex:
        log('   pause detection skipped (%s)' % ex); pz = []
    info = {'duration': round(dur, 2), 'language': '', 'summary': '', 'mood': '', 'source': 'pauses', 'note': ''}
    if ask is not None:
        try:
            mp3 = _prepare(path)
            blob = open(mp3, 'rb').read()
            if len(blob) > 18 * 1024 * 1024: raise ValueError('audio too large for the AI (%.0f MB)' % (len(blob) / 1048576))
            part = {'inlineData': {'mimeType': 'audio/mp3', 'data': base64.b64encode(blob).decode('ascii')}}
            txt = ask(SYSTEM, [{'role': 'user', 'parts': [gemini.text_part(_prompt(dur)), part]}])
            data = gemini.extract_json(txt)
            info['segments'] = _clean(data, dur, pz)
            info.update(language=str(data.get('language') or '')[:40], summary=str(data.get('summary') or '')[:300], mood=str(data.get('mood') or '')[:60], source='ai')
            log('[voice] heard %d sentences (%s), moved the scene cuts into the pauses of the voice' % (len(info['segments']), info['language'] or 'language ?'))
        except Exception as ex:
            if 'budget' in str(ex).lower(): raise
            info['note'] = 'The AI could not listen to the audio (%s); the scenes follow the pauses of the voice and no spoken words are known.' % str(ex)[:160]
            log('   [voice] %s' % info['note'])
    else:
        info['note'] = 'No AI key: the scenes follow the pauses of the voice.'
    if 'segments' not in info: info['segments'] = segments_from_pauses(dur, pz)
    return info


# ------------------------------------------------------------------ using the analysis
def timeline_text(info, t0=0.0, t1=None):
    """the voice-over timeline as it goes into the AI brief (times relative to t0)"""
    t1 = info['duration'] if t1 is None else t1
    rows = []
    for i, s in enumerate(s for s in info['segments'] if s['end'] > t0 + 0.01 and s['start'] < t1 - 0.01):
        a, b = max(0.0, s['start'] - t0), min(t1, s['end']) - t0
        line = '  %d. [%.2f - %.2f s] (%s) ' % (i + 1, a, b, s['role'])
        line += '"%s"' % s['text'] if s['text'] else '(speech, words unknown)'
        if s.get('emphasis'): line += '  key: ' + ', '.join(s['emphasis'])
        rows.append(line)
    head = 'VOICE-OVER (the video has this narration; the finished video is exactly %.2f s long; language: %s; mood: %s)\n' % (t1 - t0, info.get('language') or '?', info.get('mood') or '?')
    if info.get('summary'): head += 'About: %s\n' % info['summary']
    rules = ('RULES for a video that follows a voice-over:\n'
             '- ONE SCENE PER NUMBERED SENTENCE: the scene starts at the sentence start time and ends at its end time (use these exact times for the layers\' "start" and "end" and for background changes).\n'
             '- The on-screen text SUPPORTS the narration, it never repeats a whole sentence: show the key words / numbers / a short headline, and let them appear exactly when they are spoken '
             '(the key word starts about 0.1 s before it is said).\n'
             '- Numbers that are spoken become counters / chart values; steps become cards or lists that fill one by one; names / products become logo or chip layers; a question or hook gets one big word.\n'
             '- Keep the screen alive for the whole sentence (something moves every 1-2 seconds) but never crowd it; the next scene\'s first element appears right at the next sentence start.\n'
             '- No voice, music or sound layers in the spec (the voice-over is added by the bot). Write all on-screen text in the language of the narration unless the brief says otherwise.\n')
    return head + '\n'.join(rows) + '\n' + rules


def plan_parts(info, max_part=45.0, target=30.0, min_part=8.0):
    """for a long voice-over: group the sentences into parts at sentence boundaries -> longform outline items (exact seconds)"""
    segs = info['segments']; parts, cur = [], []
    def close():
        if not cur: return
        t0, t1 = cur[0]['start'], cur[-1]['end']
        first = next((s['text'] for s in cur if s['text']), '')
        parts.append({'title': (first[:50] or 'Part %d' % (len(parts) + 1)), 'seconds': t1 - t0, 't0': t0, 't1': t1,
                      'brief': 'Narration of this part: ' + (' '.join(s['text'] for s in cur if s['text'])[:500] or '(speech)')})
    for s in segs:
        if cur and (s['end'] - cur[0]['start'] > max_part or (cur[-1]['end'] - cur[0]['start'] >= target and s['end'] - cur[0]['start'] > target + 4)):
            close(); cur = []
        cur.append(s)
    close()
    if len(parts) > 1 and parts[-1]['seconds'] < min_part:       # a tiny last part joins the one before it
        last = parts.pop(); prev = parts[-1]
        prev.update(seconds=last['t1'] - prev['t0'], t1=last['t1'], brief=prev['brief'] + ' ' + last['brief'][len('Narration of this part: '):])
    return parts


def sub_info(info, t0, t1):
    """the analysis of one part (times start at 0)"""
    segs = []
    for s in info['segments']:
        if s['end'] <= t0 + 0.01 or s['start'] >= t1 - 0.01: continue
        segs.append(dict(s, start=round(max(s['start'], t0) - t0, 2), end=round(min(s['end'], t1) - t0, 2)))
    return dict(info, duration=round(t1 - t0, 2), segments=segs)


def snap_spec(spec, info, tol=0.4):
    """after the design: background changes, layer starts and ends that are close to a sentence boundary move exactly onto it. -> number of changes"""
    starts = [s['start'] for s in info['segments']]; bounds = sorted(set(starts + [s['end'] for s in info['segments']]))
    n = 0
    def near(t, pts):
        best = min(pts, key=lambda p: abs(p - t)); return best if abs(best - t) <= tol and abs(best - t) > 1e-6 else None
    for b in spec.get('background') or []:
        if isinstance(b, dict) and float(b.get('t', 0)) > 0.1:
            c = near(float(b['t']), starts)
            if c is not None: b['t'] = round(c, 2); n += 1
    dur = float(spec['duration'])
    for L in spec.get('layers') or []:
        if not isinstance(L, dict): continue
        if 'start' in L and float(L['start']) > 0.05:
            c = near(float(L['start']), starts)
            if c is not None and c < dur: L['start'] = round(c, 2); n += 1
        if 'end' in L and float(L['end']) < dur - 0.05:
            c = near(float(L['end']), bounds)
            if c is not None and c > float(L.get('start', 0)) + 0.3: L['end'] = round(c, 2); n += 1
    return n


def sync_report(spec, info):
    """sentences where nothing new starts on screen -> a list of text warnings (the video would feel out of step there)"""
    out = []
    layers = [L for L in spec.get('layers') or [] if isinstance(L, dict) and L.get('type') not in ('grid', 'particles', 'blob', 'transition')]
    for i, s in enumerate(info['segments']):
        if not any(s['start'] - 0.3 <= float(L.get('start', 0)) <= s['end'] - 0.2 for L in layers):
            out.append('sentence %d (%.1f-%.1f s) has no new element on screen' % (i + 1, s['start'], s['end']))
    return out


def mix(voice, sfx_wav, out_wav, dur):
    """voice (loudness-normalised) + sound effects that duck under the voice -> one wav of exactly `dur` seconds"""
    fl = 'loudnorm=I=-16:TP=-1.5:LRA=11,apad=whole_dur=%.3f,atrim=0:%.3f' % (dur, dur)
    if sfx_wav and os.path.isfile(sfx_wav):
        graph = ('[0:a]%s,asplit=2[v][vs];[1:a]volume=0.8[s];[s][vs]sidechaincompress=threshold=0.02:ratio=9:attack=15:release=350:makeup=1[d];'
                 '[v][d]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[o]' % fl)
        cmd = ['ffmpeg', '-v', 'error', '-y', '-i', voice, '-i', sfx_wav, '-filter_complex', graph, '-map', '[o]', '-ar', '48000', '-ac', '2', out_wav]
    else:
        cmd = ['ffmpeg', '-v', 'error', '-y', '-i', voice, '-af', fl, '-ar', '48000', '-ac', '2', out_wav]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0: raise RuntimeError('mixing the voice failed: %s' % r.stderr.decode('utf-8', 'ignore')[-300:])
    return out_wav


def audio_sha(path):
    import hashlib
    h = hashlib.sha1(); size = os.path.getsize(path)
    with open(path, 'rb') as f:
        h.update(f.read(1 << 20)); f.seek(max(0, size - (1 << 20))); h.update(f.read(1 << 20))
    h.update(str(size).encode()); return h.hexdigest()[:10]
