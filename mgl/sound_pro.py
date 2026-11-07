"""Premium SFX: procedural, tuned so each effect has the same spectrum / length / feel as a pro SFX pack (riser, whoosh, clack, rumble drop, shimmer hit, ticks, thud, pop). Original synthesis - no recorded audio is used."""
import numpy as np
SR = 48000
_EDGES = [0, 150, 400, 1000, 2500, 5000, 9000, 16000]
_CEN = np.array([75, 275, 700, 1750, 3750, 7000, 12500], float)
_BW = np.diff(_EDGES).astype(float)


def _tt(d): return np.arange(int(d * SR)) / SR


def shaped_noise(rng, d, bands_db):
    """white noise with a chosen energy in 7 frequency bands (dB, same bands as the analysis): 0-150, 150-400, 400-1k, 1-2.5k, 2.5-5k, 5-9k, 9-16k Hz"""
    n = int(d * SR); X = np.fft.rfft(rng.standard_normal(n)); f = np.fft.rfftfreq(n, 1 / SR)
    per_bin = np.array(bands_db, float) - 10 * np.log10(_BW)
    g = np.interp(np.log10(np.maximum(f, 30.0)), np.log10(_CEN), per_bin)
    return np.fft.irfft(X * 10 ** (g / 20.0), n)


def _env_ad(n, att, tau):
    t = np.arange(n) / SR; a = np.minimum(1.0, t / max(att, 1e-4)); return a * np.exp(-np.maximum(0, t - att) / tau)


def _pk(x, peak=1.0):
    m = np.abs(x).max(); return x / m * peak if m > 1e-9 else x


def p_whoosh(rng, d=0.9):
    """full-range pass: low body + mid + bright air, peak at ~1/3, smooth tail"""
    t = _tt(d); n = len(t)
    base = shaped_noise(rng, d, [-9, -12, -12, -9, -11, -3, -13])
    x_ = t / d; pk = 0.34
    env = np.where(x_ < pk, np.sin(0.5 * np.pi * np.minimum(x_, pk) / pk) ** 1.6, np.cos(0.5 * np.pi * np.maximum(x_ - pk, 0) / (1 - pk)) ** 2.2)
    return _pk(base * env)


def p_riser(rng, d=2.8):
    """tonal swell: a cluster of partials (1-5 kHz) growing ~20 dB, noise bed, cut off on the peak"""
    t = _tt(d); n = len(t); x = np.zeros(n)
    for fr, a in ((360, .3), (715, .6), (825, .6), (1540, 1.0), (1860, .7), (2475, .9), (2675, .9), (3310, .7), (3440, .7), (4080, .6), (4410, .6), (4740, .4), (5280, .3)):
        ph = rng.uniform(0, 6.283); vib = 1 + 0.0025 * np.sin(2 * np.pi * rng.uniform(2, 5) * t + rng.uniform(0, 6)); am = 1 + 0.25 * np.sin(2 * np.pi * rng.uniform(3, 9) * t + rng.uniform(0, 6))
        x += a * np.sin(2 * np.pi * fr * vib * t + ph) * am
    x = x / np.abs(x).max() * 0.35
    bed = shaped_noise(rng, d, [-44, -22, -11, -4, -1, -19, -28]) * 1.0
    g = 10 ** ((-26 + 26 * (t / d) ** 1.4) / 20.0)
    y = (x + bed) * g
    y[-int(0.006 * SR):] *= np.linspace(1, 0, int(0.006 * SR))
    return _pk(y)


def p_clack(rng, n=2, gap=0.13):
    """dry wooden clack(s): short body 400-2500 Hz"""
    N = int((gap * (n - 1) + 0.2) * SR); out = np.zeros(N)
    for i in range(n):
        d = 0.09; t = _tt(d); body = shaped_noise(rng, d, [-30, -14, -3, -3, -30, -37, -41]) * _env_ad(len(t), 0.0008, 0.016)
        tone = np.sin(2 * np.pi * (620 + 80 * i) * t) * np.exp(-t / 0.012) * 0.5
        c = _pk(body + tone * (np.abs(body).max() or 1)) * (1.0 - 0.15 * i); a = int(i * gap * SR); out[a:a + len(c)] += c
    return _pk(out)


def p_rumble(rng, d=1.4):
    """deep drop: crack on the front, sub that falls, rumble body 100-1000 Hz that dies away"""
    t = _tt(d); n = len(t)
    f = 46 + 70 * np.exp(-t / 0.35); ph = 2 * np.pi * np.cumsum(f) / SR; sub = np.sin(ph) * np.exp(-t / 0.55)
    body = shaped_noise(rng, d, [0, -8, -11, -26, -60, -76, -80]) * _env_ad(n, 0.004, 0.32)
    crack = shaped_noise(rng, 0.05, [-30, -14, -6, -3, -6, -14, -24]) * np.exp(-_tt(0.05) / 0.01)
    y = sub * 0.9 + body * 1.4 / max(1e-9, np.abs(body).max()) * 0.6; y[:len(crack)] += _pk(crack) * 0.5
    return _pk(y)


def p_shimmer_hit(rng, d=0.45):
    """bright airy hit: 5-16 kHz noise burst + glassy partials, 0.3 s tail"""
    t = _tt(d); n = len(t)
    nz = shaped_noise(rng, d, [-46, -52, -42, -36, -34, -13, 0]) * _env_ad(n, 0.002, 0.11)
    g = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) * a for f, a in ((9800, .5), (10900, .4), (12100, .5), (13400, .35))) * np.exp(-t / 0.13)
    return _pk(_pk(nz) + 0.35 * _pk(g))


def p_ticks(rng, n=20, speed=1.0):
    """a quick run of dry hi-frequency ticks (5-9 kHz), uneven spacing like a hand"""
    gaps = [0.055, 0.055, 0.068, 0.07, 0.072, 0.063, 0.061, 0.061, 0.053, 0.063, 0.054, 0.1, 0.099, 0.065, 0.051, 0.071, 0.06, 0.068, 0.069, 0.051]
    tot = sum(gaps[:max(0, n - 1)]) / speed + 0.1; out = np.zeros(int(tot * SR)); tm = 0.0
    for i in range(n):
        d = 0.03; x = shaped_noise(rng, d, [-44, -16, -16, -19, -16, -4, -17]) * _env_ad(int(d * SR), 0.0005, 0.005)
        x = _pk(x) * (0.55 + 0.45 * rng.random()); a = int(tm * SR); out[a:a + len(x)] += x[:len(out) - a]
        tm += (gaps[i % len(gaps)] / speed) * rng.uniform(0.9, 1.1)
    return _pk(out)


def p_thud(rng, d=0.3):
    t = _tt(d); f = 55 + 70 * np.exp(-t / 0.05); x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.09) * 0.35
    cl = shaped_noise(rng, d, [-18, -18, -21, -11, -11, -11, -1]) * np.exp(-t / 0.01); return _pk(_pk(x) + 0.5 * _pk(cl))


def p_pop(rng, d=0.12):
    t = _tt(d); return _pk(shaped_noise(rng, d, [-30, -22, -15, -8, -6, -6, -4]) * _env_ad(len(t), 0.0006, 0.012))
