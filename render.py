#!/usr/bin/env python3
"""Render a JSON scene spec to MP4 (and/or a preview contact sheet).

    python render.py examples/saas_intro.json --out out/video.mp4 --preview out/preview.png
"""
import argparse, json, os, shutil, subprocess, sys, time
import numpy as np, cv2

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from mgl import spec as S
from mgl import engine as E


def load_spec(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def check_ffmpeg():
    if shutil.which('ffmpeg') is None:
        raise SystemExit('ffmpeg not found. Install it (Ubuntu: sudo apt-get install ffmpeg).')


def preview_sheet(spec, out_png, ctx, n=12, cols=4, tile_w=480):
    """n evenly spaced frames in one PNG, each labelled with its time. Returns the list of render warnings."""
    S.setup(spec)
    dur = float(spec['duration'])
    times = [dur * (0.03 + 0.94 * i / max(1, n - 1)) for i in range(n)]
    tiles = []
    for t in times:
        fr = S.render_frame(spec, t, ctx)
        small = cv2.resize(fr, (tile_w, int(tile_w * E.H / E.W)), interpolation=cv2.INTER_AREA)
        small = np.ascontiguousarray(small)
        cv2.putText(small, '%.1fs' % t, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(small, '%.1fs' % t, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2, cv2.LINE_AA)
        tiles.append(small)
    while len(tiles) % cols: tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    cv2.imwrite(out_png, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    return ctx.warnings


_JOB = {}
DEFAULTS = {'scale': 1.0, 'fps': None, 'preset': 'medium', 'crf': None}      # run.py sets a draft here (every render_video call then makes a draft)


def _worker_frame(i):
    """runs in a worker process (fork): one finished frame as bytes (+ new warnings)"""
    spec, ctx, fps, size = _JOB['spec'], _JOB['ctx'], _JOB['fps'], _JOB['size']
    n0 = len(ctx.warnings)
    try:
        fr = S.render_frame(spec, i / fps, ctx)
        if size is not None: fr = cv2.resize(fr, size, interpolation=cv2.INTER_AREA)
        return i, fr.tobytes(), list(ctx.warnings[n0:])
    except Exception as ex:                      # one bad frame must not kill the video: the parent repeats the previous frame
        return i, None, ['frame %d failed (%s) - previous frame repeated' % (i, str(ex)[:80])]


def default_workers():
    try: w = int(os.environ.get('RENDER_WORKERS', '') or 0)
    except ValueError: w = 0
    if w > 0: return w
    return max(1, min(4, os.cpu_count() or 1))


SEG_SECONDS = 4          # a video is made in pieces of about this many seconds; each finished piece is saved


def _chain(spec, out_mp4, ctx, crf, quiet, scale, fps, preset, workers, i0=0, i1=None):
    """Never gives up on the first problem: parallel -> one worker -> one worker with a lighter encoder; a broken frame repeats the previous one."""
    last = None
    for k, (w, pr) in enumerate([(workers, preset), (1, preset), (1, 'ultrafast'), (1, 'ultrafast')]):
        try:
            if k: print('  [render] retry %d/3 (%s)' % (k, 'one worker' if k == 1 else 'one worker, light encoder'), flush=True)
            return _render_once(spec, out_mp4, ctx, crf, quiet, scale, fps, pr, w, i0, i1)
        except (Exception, SystemExit) as ex:
            last = ex; print('  [render] attempt failed: %s' % str(ex)[:200], flush=True)
            try: os.remove(out_mp4)
            except OSError: pass
    raise last


def render_video(spec, out_mp4, ctx, crf=None, quiet=False, scale=None, fps=None, preset=None, workers=None, checkpoint_dir=None):
    """Long enough videos are rendered piece by piece (SEG_SECONDS each). A finished piece is a file in checkpoint_dir, so a retry - or a
    new run of the same video - skips every piece that is already done and goes on from the exact piece where it stopped."""
    import hashlib, json as _json, shutil, tempfile
    fps_ = int(fps or DEFAULTS['fps'] or spec.get('fps', 30))
    n = int(round(float(spec['duration']) * fps_))
    seg = max(1, fps_ * SEG_SECONDS)
    if n <= seg * 1.5 and not checkpoint_dir:
        return _chain(spec, out_mp4, ctx, crf, quiet, scale, fps, preset, workers)
    check_ffmpeg(); S.setup(spec)
    own = checkpoint_dir is None
    d = checkpoint_dir or tempfile.mkdtemp(prefix='render_')
    os.makedirs(d, exist_ok=True)
    sc = DEFAULTS['scale'] if scale is None else scale
    sig = hashlib.sha1(_json.dumps([spec, fps_, sc, crf or DEFAULTS['crf'] or 16, E.W, E.H], sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]
    mp = os.path.join(d, 'render.json')
    try: man = _json.load(open(mp))
    except Exception: man = {}
    if man.get('sig') != sig:
        for f in os.listdir(d):
            if f.startswith('seg_'):
                try: os.remove(os.path.join(d, f))
                except OSError: pass
        man = {'sig': sig, 'done': []}
    bounds = [(a, min(a + seg, n)) for a in range(0, n, seg)]
    for k, (a, b) in enumerate(bounds):
        f = os.path.join(d, 'seg_%03d.mp4' % k)
        if k in man['done'] and os.path.isfile(f) and os.path.getsize(f) > 0:
            print('  [resume] piece %d/%d is already done (frames %d-%d)' % (k + 1, len(bounds), a, b), flush=True); continue
        print('  [render] piece %d/%d (frames %d-%d)' % (k + 1, len(bounds), a, b), flush=True)
        _chain(spec, f, ctx, crf, quiet, scale, fps, preset, workers, a, b)
        man['done'] = sorted(set(man['done']) | {k})
        _json.dump(man, open(mp + '.tmp', 'w')); os.replace(mp + '.tmp', mp)
        print('  [saved] piece %d/%d' % (k + 1, len(bounds)), flush=True)
    lst = os.path.join(d, 'list.txt')
    open(lst, 'w').write(''.join("file '%s'\n" % os.path.abspath(os.path.join(d, 'seg_%03d.mp4' % k)) for k in range(len(bounds))))
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', '-movflags', '+faststart', out_mp4], capture_output=True)
    if r.returncode != 0:
        for f in os.listdir(d):                      # a damaged piece: forget the pieces so the next try makes them again
            if f.startswith('seg_'): os.remove(os.path.join(d, f))
        _json.dump({'sig': sig, 'done': []}, open(mp, 'w'))
        raise SystemExit('joining the pieces failed: %s' % r.stderr.decode('utf-8', 'ignore')[-200:])
    if own: shutil.rmtree(d, ignore_errors=True)
    return ctx.warnings


def clear_checkpoint(d):
    import shutil
    if d: shutil.rmtree(d, ignore_errors=True)


def _render_once(spec, out_mp4, ctx, crf=None, quiet=False, scale=None, fps=None, preset=None, workers=None, i0=0, i1=None):
    """scale < 1 and a lower fps make a fast DRAFT; workers > 1 renders frames in parallel (same pixels as one worker)."""
    check_ffmpeg()
    S.setup(spec)
    scale = DEFAULTS['scale'] if scale is None else scale
    preset = preset or DEFAULTS['preset']
    crf = crf or DEFAULTS['crf'] or 16
    fps = int(fps or DEFAULTS['fps'] or spec.get('fps', 30))
    n = int(round(float(spec['duration']) * fps))
    i1 = n if i1 is None else i1
    ow, oh = E.W, E.H
    size = None
    if scale and scale < 0.999:
        ow, oh = max(2, int(E.W * scale) // 2 * 2), max(2, int(E.H * scale) // 2 * 2); size = (ow, oh)
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (ow, oh), '-r', str(fps),
           '-i', '-', '-an', '-c:v', 'libx264', '-preset', preset, '-crf', str(crf), '-pix_fmt', 'yuv420p',
           '-movflags', '+faststart', out_mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    workers = workers or default_workers()
    step = 15 if n >= 60 else 5
    last_frame = [None]
    try:
        if workers > 1 and (i1 - i0) >= 24 and hasattr(os, 'fork'):
            import multiprocessing as mp
            _JOB.update(spec=spec, ctx=ctx, fps=fps, size=size)
            with mp.get_context('fork').Pool(workers) as pool:
                for i, data, warns in pool.imap(_worker_frame, range(i0, i1), chunksize=4):
                    if data is None: data = last_frame[0]
                    if data is None: raise RuntimeError('first frame failed: ' + '; '.join(warns))
                    last_frame[0] = data
                    p.stdin.write(data)
                    for w in warns:
                        if w not in ctx.warnings: ctx.warnings.append(w)
                    if not quiet and i % step == 0:
                        print('  frame %d/%d  (%.0fs, %d workers)' % (i, n, time.time() - t0, workers), flush=True)
        else:
            for i in range(i0, i1):
                try:
                    fr = S.render_frame(spec, i / fps, ctx)
                    if size is not None: fr = cv2.resize(fr, size, interpolation=cv2.INTER_AREA)
                    last_frame[0] = fr.tobytes()
                except Exception as ex:
                    if last_frame[0] is None: raise
                    ctx.warnings.append('frame %d failed (%s) - previous frame repeated' % (i, str(ex)[:80]))
                p.stdin.write(last_frame[0])
                if not quiet and i % step == 0:
                    print('  frame %d/%d  (%.0fs)' % (i, n, time.time() - t0), flush=True)
        print('  frame %d/%d  (%.0fs)' % (i1, n, time.time() - t0), flush=True) if not quiet else None
        p.stdin.close()
    except BrokenPipeError:
        pass
    except BaseException:
        try: p.kill()
        except Exception: pass
        raise
    rc = p.wait()
    if rc != 0:
        raise SystemExit('ffmpeg failed with exit code %d' % rc)
    return ctx.warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec')
    ap.add_argument('--out', default='out/video.mp4')
    ap.add_argument('--preview', default=None)
    ap.add_argument('--preview-only', action='store_true')
    a = ap.parse_args()
    spec = load_spec(a.spec)
    errs, warns = S.validate(spec, ROOT)
    for w in warns: print('warning:', w)
    if errs:
        print('SPEC ERRORS:')
        for e in errs: print(' -', e)
        raise SystemExit(1)
    ctx = S.Context(ROOT)
    if a.preview:
        preview_sheet(spec, a.preview, ctx)
        print('preview ->', a.preview)
    if not a.preview_only:
        render_video(spec, a.out, ctx)
        print('video ->', a.out)
    for w in ctx.warnings: print('render warning:', w)


if __name__ == '__main__':
    main()
