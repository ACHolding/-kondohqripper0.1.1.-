#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AC'S HQRIPPER 0.2 -- High Quality Rip DAW
Credit to SiIvaGunner [c] 1999-2026 [c] Haltmann Works 1999-20XX

Single-file DAW: multitrack timeline, transport, mixer/inspector, undo/redo,
BPM + key analysis, phase-vocoder time-stretch, pitch shift, 3-band EQ,
built-in synths, and the HQ Rip / rave.dj mashup engine.

    python program.py            # launch the app
    python program.py --selftest # headless engine test (no GUI, no audio device)

files = OFF  ->  no local file import/browse. Sources are URLs (yt-dlp) or the
built-in synths. Exports go to the typed destination folder.
"""

import sys, os, re, json, math, time, queue, random, shutil, subprocess, tempfile
import threading, importlib, wave
from datetime import datetime
from fractions import Fraction

if sys.version_info < (3, 8):
    raise SystemExit("Python 3.8+ required (got %s)" % sys.version.split()[0])

# pr files = off
files = False

# ---------------------------------------------------------------------------
# Optional-dependency loader (never blocks on a dep that already failed once)
# ---------------------------------------------------------------------------
_DEPFILE = os.path.join(os.path.expanduser("~"), ".hqripper_deps.json")


def _load_failed():
    try:
        with open(_DEPFILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


_FAILED = _load_failed()


def _try_import(mod):
    try:
        return importlib.import_module(mod)
    except Exception:          # ImportError, or OSError for missing PortAudio etc.
        return None


def ensure(mod, pkg):
    m = _try_import(mod)
    if m is not None or os.environ.get("HQ_NO_INSTALL") or pkg in _FAILED:
        return m
    print("[hqripper] installing %s ..." % pkg)
    for extra in ([], ["--break-system-packages"]):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg] + extra,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            importlib.invalidate_caches()
            m = _try_import(mod)
            if m is not None:
                return m
        except Exception:
            pass
    _FAILED.add(pkg)
    try:
        with open(_DEPFILE, "w") as f:
            json.dump(sorted(_FAILED), f)
    except Exception:
        pass
    return None


np = ensure("numpy", "numpy")
if np is None:
    raise SystemExit("numpy is required: pip install numpy")
signal = ensure("scipy.signal", "scipy")
sf = ensure("soundfile", "soundfile")
yt_dlp = ensure("yt_dlp", "yt-dlp")
sd = ensure("sounddevice", "sounddevice")
FFMPEG = shutil.which("ffmpeg")

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog, scrolledtext
except Exception:
    tk = None

APP = "ac's hqripper 0.2"
SR = 44100
QUOTES = ["Please read the channel description.", "GRAND DAD?! FLEENSTONES?!",
          "Todokete...", "It's the Nutshack!", "Now that's a high quality rip!"]
MAX_SECONDS = 15 * 60

PATCH_NOTES = """ac's hqripper 0.2 -- Patch Notes
==================================

NEW: it's a real DAW now
 * Multitrack timeline: waveforms, bar/beat grid, zoom, scroll, snap
 * Drag clips, Mute / Solo, volume, pan, 3-band EQ, pitch, BPM-sync per track
 * Transport: play/pause/stop, loop, seek by clicking the ruler, live meter
 * Live mixing during playback (mute/solo/volume/pan are instant)
 * Undo / Redo (Ctrl+Z / Ctrl+Y), duplicate + delete tracks
 * Built-in synths: drums, bass, pad (project works with no network)
 * HQ Rip Builder: T1 = game OST bed, T2 = joke source, bait-and-switch drop
   modes: HQ Rip | rave.dj | Blend | Alternate | Layer | Sidechain
 * Export mixdown: WAV / MP3 (320k) / MP4 with fade-out + normalize
 * files = off is still locked: URL sources only

FIXED
 * Time-stretch no longer changes pitch (phase vocoder, was plain resample)
 * Key / BPM detection vectorised (was a Python loop over every FFT bin)
 * Key detection now major/minor aware (Krumhansl profiles)
 * Half/double-time BPM folding when matching two tracks
 * rave.dj mode: crossfade direction bug + per-chunk filter edge clicks
 * EQ is now flat when all bands = 1 (was a phase-cancelling filter sum)
 * Stereo end-to-end (was collapsed to mono)
 * Export: ext.replace() path bug, silently-swallowed ffmpeg/MP3/MP4 errors
 * Worker threads no longer touch Tk widgets (queue-pumped UI)
 * Stale-download bug (shared temp dir picked old files), temp cleanup
 * pydub removed (dead on Python 3.13+: audioop was deleted); ffmpeg/soundfile
 * No longer requires Python 3.14; startup doesn't block on pip retries
 * Preview buttons now actually do something

\"Please read the channel description.\""""

COPYRIGHT_TEXT = """ac's hqripper 0.2

Credit to SiIvaGunner
[c] 1999-2026

[c] Haltmann Works 1999-20XX

High Quality Video Game Rips(tm)

\"Please read the channel description.\""""

THEMES = {
    'dark': {
        'bg': '#000000', 'fg': '#eeeeee', 'panel': '#0e0e0e', 'entry_bg': '#0a0a0a',
        'entry_fg': '#ffffff', 'accent': '#1e6fbf', 'menu_bg': '#000000',
        'toolbar': '#050505', 'status': '#000000', 'console_bg': '#000000',
        'console_fg': '#00ff88', 'border': '#1e6fbf', 'muted': '#8a8a8a',
        'btn': '#1e6fbf', 'btn_fg': '#ffffff', 'btn_active': '#2b86e0',
        'lane1': '#0a0a0a', 'lane2': '#121212', 'grid': '#1c1c1c', 'bar': '#333333',
        'hdr': '#0e0e0e', 'hdr_sel': '#1a2a3d',
    },
    'light': {
        'bg': '#f0f0f0', 'fg': '#000000', 'panel': '#e8e8e8', 'entry_bg': '#ffffff',
        'entry_fg': '#000000', 'accent': '#1e6fbf', 'menu_bg': '#f0f0f0',
        'toolbar': '#e4e4e4', 'status': '#ece9d8', 'console_bg': '#0d0d1a',
        'console_fg': '#00ff88', 'border': '#a0a0a0', 'muted': '#666666',
        'btn': '#1e6fbf', 'btn_fg': '#ffffff', 'btn_active': '#155a9c',
        'lane1': '#fafafa', 'lane2': '#eeeeee', 'grid': '#dddddd', 'bar': '#b8b8b8',
        'hdr': '#e4e4e4', 'hdr_sel': '#c9def5',
    },
    'blue': {
        'bg': '#0b2a4a', 'fg': '#e6f2ff', 'panel': '#123a66', 'entry_bg': '#0a1f38',
        'entry_fg': '#ffffff', 'accent': '#2f8fe8', 'menu_bg': '#0b2a4a',
        'toolbar': '#0f3459', 'status': '#08213b', 'console_bg': '#061a30',
        'console_fg': '#7ee8ff', 'border': '#2f8fe8', 'muted': '#9ec3e8',
        'btn': '#1f7fd6', 'btn_fg': '#ffffff', 'btn_active': '#3a9bf0',
        'lane1': '#0a2340', 'lane2': '#0d2b4d', 'grid': '#173d68', 'bar': '#2a5a92',
        'hdr': '#0f3459', 'hdr_sel': '#1d5089',
    },
}
THEME_LABELS = {'dark': 'Dark Mode (Black)', 'light': 'Light Mode', 'blue': 'Blue Mode'}
THEME_ORDER = ['dark', 'light', 'blue']
TRACK_COLORS = ['#3aa0ff', '#ff7a45', '#43d17a', '#c86bff', '#ffd23f', '#ff5c8a', '#3fe0d0', '#9aa7ff']
NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# ---------------------------------------------------------------------------
# DSP
# ---------------------------------------------------------------------------


def to_stereo(y):
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        y = np.stack([y, y], 1)
    elif y.shape[1] == 1:
        y = np.repeat(y, 2, 1)
    elif y.shape[1] > 2:
        y = y[:, :2]
    return np.ascontiguousarray(y)


def resample_to_len(y, n):
    """Resample (n0,ch) audio to exactly n samples."""
    n0 = len(y)
    if n0 == n or n0 < 2 or n < 1:
        return y[:n] if n0 > n else y
    if signal is not None:
        fr = Fraction(n, n0).limit_denominator(1000)
        out = signal.resample_poly(y, fr.numerator, fr.denominator, axis=0).astype(np.float32)
    else:
        x = np.linspace(0, n0 - 1, n)
        out = np.stack([np.interp(x, np.arange(n0), y[:, c]) for c in range(y.shape[1])], 1).astype(np.float32)
    if len(out) < n:
        out = np.pad(out, ((0, n - len(out)), (0, 0)))
    return np.ascontiguousarray(out[:n])


def resample_sr(y, sr_in, sr_out):
    if sr_in == sr_out:
        return y
    return resample_to_len(y, int(round(len(y) * sr_out / sr_in)))


def read_wav_stdlib(path):
    with wave.open(path, 'rb') as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        d = np.frombuffer(raw, '<i2').astype(np.float32) / 32768
    elif sw == 1:
        d = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif sw == 4:
        d = np.frombuffer(raw, '<i4').astype(np.float32) / 2147483648
    else:
        raise RuntimeError("Unsupported WAV sample width %d" % sw)
    return d.reshape(-1, ch), sr


def load_audio(path):
    """Decode any audio file -> stereo float32 @ SR."""
    d = sr = None
    if sf is not None:
        try:
            d, sr = sf.read(path, dtype='float32', always_2d=True)
        except Exception:
            d = None
    if d is None and path.lower().endswith('.wav'):
        try:
            d, sr = read_wav_stdlib(path)
        except Exception:
            d = None
    if d is None:
        if not FFMPEG:
            raise RuntimeError("Can't decode this audio. Install ffmpeg (or pip install soundfile).")
        out = path + ".dec.wav"
        r = subprocess.run([FFMPEG, '-y', '-i', path, '-ar', str(SR), '-ac', '2', out],
                           capture_output=True)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError("ffmpeg decode failed: " + r.stderr.decode(errors='ignore')[-300:])
        try:
            d, sr = read_wav_stdlib(out)
        finally:
            try: os.remove(out)
            except OSError: pass
    y = resample_sr(to_stereo(d), sr, SR)
    return np.ascontiguousarray(y[:MAX_SECONDS * SR])


def _frames(x, n, hop):
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    nf = 1 + (len(x) - n) // hop
    return x[np.arange(n)[None, :] + hop * np.arange(nf)[:, None]]


def _pv_channel(x, rate, n_fft=2048, hop=512):
    """Phase-vocoder time-stretch of a mono channel. rate>1 = faster/shorter."""
    x = x.astype(np.float32)
    win = np.hanning(n_fft).astype(np.float32)
    pad = n_fft // 2
    xp = np.pad(x, (pad, pad + n_fft))
    S = np.fft.rfft(_frames(xp, n_fft, hop) * win, axis=1).astype(np.complex64)
    nfr, nb = S.shape
    mag, ph = np.abs(S), np.angle(S)
    omega = (2 * np.pi * hop * np.arange(nb) / n_fft).astype(np.float32)
    d = ph[1:] - ph[:-1] - omega
    d -= 2 * np.pi * np.round(d / (2 * np.pi))
    adv = omega + d
    steps = np.arange(0, nfr - 1, rate)
    n_out = len(steps)
    idx = steps.astype(int)
    frac = (steps - idx).astype(np.float32)[:, None]
    M = mag[idx] * (1 - frac) + mag[idx + 1] * frac
    P = np.empty((n_out, nb), dtype=np.float32)
    acc = ph[0].copy()
    for k in range(n_out):
        P[k] = acc
        acc = acc + adv[idx[k]]
    frames = np.fft.irfft(M * np.exp(1j * P), n=n_fft, axis=1).astype(np.float32) * win
    out = np.zeros(hop * (n_out - 1) + n_fft, dtype=np.float32)
    for k in range(n_out):
        out[k * hop:k * hop + n_fft] += frames[k]
    out /= 1.5                                  # hann^2 sum at 75% overlap
    target = int(round(len(x) / rate))
    out = out[pad:pad + target]
    if len(out) < target:
        out = np.pad(out, (0, target - len(out)))
    return out


def time_stretch(y, rate):
    """Change tempo without changing pitch. rate = new_speed / old_speed."""
    if abs(rate - 1.0) < 1e-3 or len(y) < 4096:
        return y
    cols = [_pv_channel(y[:, c], rate) for c in range(y.shape[1])]
    return np.ascontiguousarray(np.stack(cols, 1).astype(np.float32))


def pitch_shift(y, semitones):
    if semitones == 0 or len(y) < 4096:
        return y
    f = 2.0 ** (semitones / 12.0)
    return resample_to_len(time_stretch(y, 1.0 / f), len(y))


def eq3(y, sr, lo=1.0, mid=1.0, hi=1.0):
    """Zero-phase 3-band EQ (crossovers ~200 Hz / 2 kHz). Flat when all bands = 1."""
    if abs(lo - 1) < .01 and abs(mid - 1) < .01 and abs(hi - 1) < .01:
        return y
    N = 8192
    hop = N // 2
    win = np.hanning(N + 1)[:-1].astype(np.float32)
    f = np.fft.rfftfreq(N, 1.0 / sr)
    g = np.interp(np.log10(np.maximum(f, 1.0)),
                  np.log10([1.0, 140.0, 280.0, 1400.0, 2800.0, sr / 2.0]),
                  [lo, lo, mid, mid, hi, hi]).astype(np.float32)
    n = len(y)
    yp = np.pad(y, ((N, N + hop), (0, 0)))
    nfr = 1 + (len(yp) - N) // hop
    out = np.zeros_like(yp)
    ar = np.arange(N)[None, :]
    for b in range(0, nfr, 128):
        ks = np.arange(b, min(nfr, b + 128))
        seg = yp[ks[:, None] * hop + ar]                            # (k,N,ch)
        R = np.fft.irfft(np.fft.rfft(seg * win[None, :, None], axis=1) * g[None, :, None],
                         n=N, axis=1).astype(np.float32)
        for j, k in enumerate(ks):
            out[k * hop:k * hop + N] += R[j]
    return np.ascontiguousarray(out[N:N + n])


def smooth(x, w):
    x = np.asarray(x, dtype=np.float64)
    w = max(1, int(w))
    if len(x) < w + 2:
        return np.full(len(x), x.mean() if len(x) else 0.0)
    c = np.cumsum(np.insert(x, 0, 0.0))
    o = (c[w:] - c[:-w]) / w
    left = w // 2
    right = len(x) - len(o) - left
    return np.concatenate([np.full(left, o[0]), o, np.full(right, o[-1])])


def normalize(y, db=-3.0):
    pk = float(np.max(np.abs(y))) if len(y) else 0.0
    return y * (10 ** (db / 20.0) / pk) if pk > 0 else y


def fade(y, fi=0.05, fo=2.0):
    n = len(y)
    env = np.ones(n, dtype=np.float32)
    a, b = int(SR * fi), int(SR * fo)
    if 0 < a < n: env[:a] = np.linspace(0, 1, a)
    if 0 < b < n: env[-b:] = np.minimum(env[-b:], np.linspace(1, 0, b))
    return y * env[:, None]


def detect_bpm(y, sr=SR):
    """Spectral-flux onset envelope -> autocorrelation with a tempo prior. Returns BPM or None."""
    x = y.mean(axis=1) if y.ndim > 1 else y
    if len(x) < sr * 4:
        return None
    if len(x) > sr * 120:
        a = int(len(x) * 0.1)
        x = x[a:a + sr * 90]
    hop, n_fft = 512, 1024
    mag = np.abs(np.fft.rfft(_frames(x, n_fft, hop) * np.hanning(n_fft), axis=1))
    mag = np.log1p(mag * 10)
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    flux = flux - flux.mean()
    if flux.std() < 1e-6:
        return None
    ac = np.fft.irfft(np.abs(np.fft.rfft(flux, n=2 * len(flux))) ** 2)[:len(flux)]
    ac = ac / (ac[0] + 1e-9)
    fps = sr / hop
    bpms = np.arange(70, 180.01, 0.25)
    lags = 60.0 * fps / bpms
    grid = np.arange(len(ac))
    score = np.interp(lags, grid, ac) + 0.5 * np.interp(2 * lags, grid, ac)
    prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
    return float(bpms[int(np.argmax(score * prior))])


_KMAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KMIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def detect_key(y, sr=SR):
    """Chromagram + Krumhansl profiles -> (tonic_pitch_class, is_minor) or None."""
    x = y.mean(axis=1) if y.ndim > 1 else y
    if len(x) < sr:
        return None
    a = len(x) // 4
    seg = x[a:a + sr * 60] if len(x) > sr * 8 else x
    n_fft, hop = 8192, 4096
    mag = np.abs(np.fft.rfft(_frames(seg, n_fft, hop) * np.hanning(n_fft), axis=1)).mean(axis=0)
    f = np.fft.rfftfreq(n_fft, 1.0 / sr)
    m = (f > 60) & (f < 2000)
    pc = np.round(69 + 12 * np.log2(f[m] / 440.0)).astype(int) % 12
    chroma = np.bincount(pc, weights=mag[m], minlength=12)
    if chroma.sum() <= 0:
        return None
    best, bs = (0, False), -9
    for k in range(12):
        for prof, minor in ((_KMAJ, False), (_KMIN, True)):
            s = np.corrcoef(np.roll(chroma, -k), prof)[0, 1]
            if s > bs:
                best, bs = (k, minor), s
    return best


def key_name(k):
    return "%s %s" % (NOTE[k[0] % 12], "min" if k[1] else "maj") if k else "?"


def key_root_major(k):
    return (k[0] + 3) % 12 if k[1] else k[0] % 12


def key_shift(src, dst):
    """Shortest semitone shift taking src key to dst (via relative-major roots)."""
    d = (key_root_major(dst) - key_root_major(src)) % 12
    return d - 12 if d > 6 else d


def phrase_len(sr, bpm, bars=8):
    return max(1, int((60.0 / bpm) * sr * 4 * bars))


def fold_bpm(b, ref):
    """Fold half/double-time so b sits within ~1.41x of ref."""
    if not b or not ref:
        return b
    while b > ref * 1.41: b /= 2
    while b < ref / 1.41: b *= 2
    return b


# --- mashup modes (all stereo (n,2)) ---------------------------------------

def mix_hqrip(y1, y2, sr, bpm):
    """SiIvaGunner lore: T1 = advertised OST bed, T2 = joke overlay, bait-and-switch drop."""
    n = len(y1)
    intro = min(phrase_len(sr, bpm, 8), n // 3)
    bed = eq3(y1, sr, 1.25, 0.85, 0.35)
    joke = eq3(y2, sr, 0.25, 1.05, 1.25)
    je = smooth(np.abs(joke).max(axis=1), sr // 20)
    if je.max() > 0: je = je / je.max()
    bed = bed * (1.0 - 0.45 * je)[:, None]
    mash = bed * 0.7 + joke * 0.65
    env = np.ones(n, dtype=np.float32)
    if intro > 0:
        env[:intro] = 0.0
        xf = min(phrase_len(sr, bpm, 1), max(1, n - intro))
        env[intro:intro + xf] = np.linspace(0, 1, xf)
    rip = y1 * (1 - env)[:, None] + mash * env[:, None]
    outro = phrase_len(sr, bpm, 4)
    if outro < n:
        oe = np.linspace(0, 1, outro, dtype=np.float32)[:, None]
        rip[-outro:] = rip[-outro:] * (1 - 0.35 * oe) + joke[-outro:] * (0.55 * oe)
    return rip.astype(np.float32)


def mix_rave(y1, y2, sr, bpm):
    """rave.dj-style: phrase ownership swaps with a 1-bar crossfade from the previous owner."""
    ph = phrase_len(sr, bpm, 8)
    xf = max(1, ph // 8)
    n = len(y1)
    lead = np.zeros_like(y1)
    use1, i = True, 0
    while i < n:
        end = min(i + ph, n)
        own, oth = (y1, y2) if use1 else (y2, y1)
        chunk = own[i:end].copy()
        if i > 0 and end - i > xf * 2:
            ramp = np.linspace(0, 1, xf, dtype=np.float32)[:, None]
            chunk[:xf] = oth[i:i + xf] * (1 - ramp) + own[i:i + xf] * ramp
        lead[i:end] = chunk
        use1, i = not use1, end
    return (eq3(y1, sr, 1.1, 0.5, 0.3) * 0.35 + eq3(lead, sr, 0.5, 1.0, 1.1) * 0.75).astype(np.float32)


def mix_blend(y1, y2, sr=SR, bpm=120):
    return ((y1 + y2) * 0.5).astype(np.float32)


def mix_alt(y1, y2, sr, bpm, bars=4):
    step = phrase_len(sr, bpm, bars)
    out = np.zeros_like(y1)
    use1 = True
    for i in range(0, len(y1), step):
        out[i:i + step] = (y1 if use1 else y2)[i:i + step]
        use1 = not use1
    return out


def mix_layer(y1, y2, sr, bpm=120):
    return (eq3(y1, sr, 1.2, 0.7, 0.4) * 0.6 + eq3(y2, sr, 0.4, 0.7, 1.2) * 0.6).astype(np.float32)


def mix_sc(y1, y2, sr, bpm):
    beat = max(2, int((60.0 / bpm) * sr))
    d = int(beat * 0.3)
    pulse = np.concatenate([np.linspace(1, 0.3, d // 2), np.linspace(0.3, 1, d - d // 2),
                            np.ones(beat - d)]).astype(np.float32)
    env = np.tile(pulse, len(y1) // beat + 1)[:len(y1)]
    return (y1 * 0.7 + y2 * env[:, None] * 0.5).astype(np.float32)


MIX_MODES = [("HQ Rip (SiIva lore)", "hqrip"), ("rave.dj", "rave"), ("Blend", "blend"),
             ("Alternate", "alternate"), ("Layer", "layer"), ("Sidechain", "sidechain")]


def build_rip(a, b, mode, bpm_target, align_key, log, prog):
    """a,b: Track objects (raw audio). Returns (audio, target_bpm)."""
    y1, y2 = a.audio, b.audio
    bpm1 = a.bpm or detect_bpm(y1) or 120.0
    bpm2 = fold_bpm(b.bpm or detect_bpm(y2) or 120.0, bpm1)
    tb = bpm_target or round(bpm1)
    log("  T1 (OST):  %.1f BPM  %s" % (bpm1, key_name(a.key or detect_key(y1))))
    log("  T2 (Joke): %.1f BPM  %s" % (bpm2, key_name(b.key or detect_key(y2))))
    log("  Target BPM: %s" % tb)
    prog(30)
    y1 = time_stretch(y1, tb / bpm1)
    prog(45)
    y2 = time_stretch(y2, tb / bpm2)
    prog(60)
    if align_key:
        k1, k2 = a.key or detect_key(a.audio), b.key or detect_key(b.audio)
        if k1 and k2:
            st = key_shift(k2, k1)
            if st:
                log("  Key shift T2: %+d st -> %s" % (st, key_name(k1)))
                y2 = pitch_shift(y2, st)
    ml = max(len(y1), len(y2))
    if len(y1) < ml: y1 = np.tile(y1, (int(np.ceil(ml / len(y1))), 1))[:ml]
    if len(y2) < ml: y2 = np.tile(y2, (int(np.ceil(ml / len(y2))), 1))[:ml]
    y1, y2 = normalize(y1, -6), normalize(y2, -6)
    prog(75)
    fn = {'hqrip': mix_hqrip, 'rave': mix_rave, 'blend': mix_blend, 'alternate': mix_alt,
          'layer': mix_layer, 'sidechain': mix_sc}.get(mode, mix_hqrip)
    return fn(y1, y2, SR, tb).astype(np.float32), float(tb)


# --- synths ---------------------------------------------------------------

def synth_drums(bpm, bars=4):
    step = 60.0 / bpm / 4
    n = int(step * 16 * bars * SR)
    y = np.zeros(n, dtype=np.float32)
    rng = np.random.RandomState(7)

    def put(sig, t):
        s = int(t * SR)
        e = min(n, s + len(sig))
        if e > s: y[s:e] += sig[:e - s]

    t = np.arange(int(.4 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(48 + 110 * np.exp(-t * 38)) / SR) * np.exp(-t * 8) * 0.9
    t2 = np.arange(int(.25 * SR)) / SR
    snare = (rng.randn(len(t2)) * np.exp(-t2 * 20) * .5 + np.sin(2 * np.pi * 190 * t2) * np.exp(-t2 * 28) * .4)
    t3 = np.arange(int(.08 * SR)) / SR
    hat = np.diff(rng.randn(len(t3) + 1)) * np.exp(-t3 * 70) * .25
    for bar in range(bars):
        base = bar * 16
        for s in (0, 8, 10): put(kick, (base + s) * step)
        for s in (4, 12): put(snare, (base + s) * step)
        for s in range(0, 16, 2): put(hat, (base + s) * step)
    return to_stereo(y * 0.8)


def synth_bass(bpm, bars=4):
    beat = 60.0 / bpm
    n = int(beat * 4 * bars * SR)
    y = np.zeros(n, dtype=np.float32)
    pat = [0, 0, 12, 0, 3, 0, 7, 5]                       # A minor riff, 8ths
    dur = beat / 2
    t = np.arange(int(dur * SR)) / SR
    env = np.exp(-t * 3.5) * np.minimum(1, t * 300)
    for i in range(int(bars * 8)):
        f = 55.0 * 2 ** (pat[i % 8] / 12.0)
        w = (np.sin(2 * np.pi * f * t) + .5 * np.sin(4 * np.pi * f * t) + .25 * np.sin(6 * np.pi * f * t)) * env
        s = int(i * dur * SR)
        e = min(n, s + len(w))
        y[s:e] += w[:e - s] * 0.45
    return to_stereo(y)


def synth_pad(bpm, bars=4):
    beat = 60.0 / bpm
    n = int(beat * 4 * bars * SR)
    L, R = np.zeros(n, np.float32), np.zeros(n, np.float32)
    bt = np.arange(int(beat * 4 * SR)) / SR
    env = np.minimum(1, bt / 0.4) * np.minimum(1, (bt[-1] - bt) / 0.5)
    for bar in range(bars):
        s = int(bar * beat * 4 * SR)
        for j, semi in enumerate((0, 3, 7, 10)):        # Am7
            f = 220.0 * 2 ** (semi / 12.0)
            for det, pan in ((0.997, 0.3), (1.0, 0.5), (1.003, 0.7)):
                w = np.sin(2 * np.pi * f * det * bt + j) * env * 0.05
                e = min(n, s + len(w))
                L[s:e] += w[:e - s] * (1 - pan)
                R[s:e] += w[:e - s] * pan
    return np.stack([L, R], 1) * 1.6


# --- I/O ------------------------------------------------------------------

def write_wav(path, y, sr=SR):
    y = np.clip(y, -1, 1)
    if sf is not None:
        sf.write(path, y, sr, subtype='PCM_16')
        return
    with wave.open(path, 'wb') as w:
        w.setnchannels(y.shape[1]); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y * 32767).astype('<i2').tobytes())


def export_audio(y, path, log=print):
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    if ext == '.wav':
        write_wav(path, y)
        return path
    tmpd = tempfile.mkdtemp(prefix="hqexp_")
    try:
        wav = os.path.join(tmpd, "mix.wav")
        write_wav(wav, y)
        if ext == '.mp3':
            if FFMPEG:
                r = subprocess.run([FFMPEG, '-y', '-i', wav, '-codec:a', 'libmp3lame', '-b:a', '320k', path],
                                   capture_output=True)
                if r.returncode != 0:
                    raise RuntimeError("ffmpeg MP3 encode failed: " + r.stderr.decode(errors='ignore')[-300:])
            elif sf is not None and 'MP3' in sf.available_formats():
                sf.write(path, np.clip(y, -1, 1), SR, format='MP3')
            else:
                fb = os.path.splitext(path)[0] + ".wav"
                shutil.copy(wav, fb)
                raise RuntimeError("MP3 needs ffmpeg. Saved WAV instead: " + fb)
        elif ext == '.mp4':
            if not FFMPEG:
                fb = os.path.splitext(path)[0] + ".wav"
                shutil.copy(wav, fb)
                raise RuntimeError("MP4 needs ffmpeg. Saved WAV instead: " + fb)
            dur = len(y) / SR
            r = subprocess.run([FFMPEG, '-y', '-f', 'lavfi', '-i', 'color=c=0x1a1a2e:s=1920x1080:r=5:d=%.3f' % dur,
                                '-i', wav, '-c:v', 'libx264', '-tune', 'stillimage', '-pix_fmt', 'yuv420p',
                                '-c:a', 'aac', '-b:a', '320k', '-shortest', path], capture_output=True)
            if r.returncode != 0:
                raise RuntimeError("ffmpeg MP4 encode failed: " + r.stderr.decode(errors='ignore')[-300:])
        else:
            raise RuntimeError("Unknown format " + ext)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    return path


def fetch_url(url, tmp, log, name="src"):
    """URL-only source fetch (files = off). Returns (path, title)."""
    if not re.match(r'^https?://', url.strip(), re.I):
        raise RuntimeError("files = off: paste an http(s) URL (YouTube, SoundCloud, ...). "
                           "Local file paths are disabled.")
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed (pip install yt-dlp).")
    log("[DL] %s" % url[:70])
    opts = {'format': 'bestaudio/best', 'outtmpl': os.path.join(tmp, name + '.%(ext)s'),
            'noplaylist': True, 'quiet': True, 'no_warnings': True, 'socket_timeout': 30}
    if FFMPEG:
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True) or {}
    if info.get('entries'):
        info = next((e for e in info['entries'] if e), {})
    title = info.get('title') or "Track"
    cands = [f for f in os.listdir(tmp) if f.startswith(name + '.') and not f.endswith(('.part', '.ytdl'))]
    if not cands:
        raise RuntimeError("Download failed (no output file).")
    cands.sort(key=lambda f: os.path.getmtime(os.path.join(tmp, f)))
    return os.path.join(tmp, cands[-1]), title


# ---------------------------------------------------------------------------
# Project model
# ---------------------------------------------------------------------------
PK = 256


def compute_peaks(y):
    a = np.abs(y).max(axis=1)
    pad = (-len(a)) % PK
    if pad: a = np.pad(a, (0, pad))
    return a.reshape(-1, PK).max(axis=1)


class Track:
    _n = 0

    def __init__(self, name, audio, start=0.0, source=""):
        Track._n += 1
        self.id = Track._n
        self.name, self.source, self.start = name, source, float(start)
        self.audio = to_stereo(audio)
        self.vol, self.pan, self.mute, self.solo = 1.0, 0.0, False, False
        self.eq, self.pitch, self.sync = [1.0, 1.0, 1.0], 0, False
        self.bpm, self.key = None, None
        self.color = TRACK_COLORS[(self.id - 1) % len(TRACK_COLORS)]
        self.proc = self.audio
        self.proc_key = self.want_key(0)
        self.peaks = compute_peaks(self.audio)
        self.busy = False

    def want_key(self, master_bpm):
        s = bool(self.sync and self.bpm)
        return (tuple(round(e, 2) for e in self.eq), int(self.pitch), round(master_bpm, 2) if s else None)

    def build(self, master_bpm):
        y = self.audio
        if self.sync and self.bpm and abs(master_bpm - self.bpm) > 0.05:
            y = time_stretch(y, master_bpm / self.bpm)
        if self.pitch:
            y = pitch_shift(y, self.pitch)
        return eq3(y, SR, *self.eq)

    def params(self):
        return dict(name=self.name, start=self.start, vol=self.vol, pan=self.pan, mute=self.mute,
                    solo=self.solo, eq=list(self.eq), pitch=self.pitch, sync=self.sync)

    def apply(self, p):
        for k, v in p.items():
            setattr(self, k, list(v) if k == 'eq' else v)

    def duplicate(self):
        t = Track(self.name + " copy", self.audio, self.start + 0.0, self.source)
        t.apply({k: v for k, v in self.params().items() if k != 'name'})
        t.bpm, t.key = self.bpm, self.key
        t.proc, t.proc_key, t.peaks = self.proc, self.proc_key, self.peaks
        return t


class Project:
    def __init__(self):
        self.tracks, self.bpm, self.master = [], 120.0, 0.9

    def length_samples(self):
        return max([int(t.start * SR) + len(t.proc) for t in list(self.tracks)] or [0])

    def mix_block(self, pos, n):
        out = np.zeros((n, 2), dtype=np.float32)
        tr = list(self.tracks)
        any_solo = any(t.solo for t in tr)
        for t in tr:
            if t.mute or (any_solo and not t.solo):
                continue
            y = t.proc
            s = int(t.start * SR)
            a, b = max(pos, s), min(pos + n, s + len(y))
            if b <= a:
                continue
            seg = y[a - s:b - s]
            gl, gr = t.vol * min(1.0, 1.0 - t.pan), t.vol * min(1.0, 1.0 + t.pan)
            out[a - pos:b - pos, 0] += seg[:, 0] * gl
            out[a - pos:b - pos, 1] += seg[:, 1] * gr
        return out * self.master

    def render(self, start=0, end=None):
        end = self.length_samples() if end is None else end
        return self.mix_block(start, max(0, end - start))


# ---------------------------------------------------------------------------
# Player (live-mixing via sounddevice; system-player fallback)
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, app):
        self.app = app
        self.pos, self.playing, self.ended, self.loop = 0, False, False, False
        self.stream, self.proc, self.mode, self.peak = None, None, None, 0.0
        self.t0 = self.p0 = 0

    def position(self):
        if self.mode == 'ext' and self.playing:
            p = self.p0 + int((time.time() - self.t0) * SR)
            if self.proc is not None and self.proc.poll() is not None:
                self.ended = True
            return min(p, self.app.project.length_samples())
        return self.pos

    def _cb(self, out, frames, time_info, status):
        proj = self.app.project
        total = proj.length_samples()
        mix = np.clip(proj.mix_block(self.pos, frames), -1, 1)
        out[:] = mix
        self.peak = float(np.abs(mix).max()) if frames else 0.0
        self.pos += frames
        if self.pos >= total:
            if self.loop and total > 0:
                self.pos = 0
            else:
                self.ended = True
                raise sd.CallbackStop

    def start(self):
        if self.playing:
            return True
        self.ended = False
        if sd is not None:
            try:
                self.stream = sd.OutputStream(samplerate=SR, channels=2, dtype='float32',
                                              blocksize=1024, callback=self._cb)
                self.stream.start()
                self.playing, self.mode = True, 'sd'
                return True
            except Exception as e:
                self.app.log("[audio] live output unavailable (%s) -> using system player" % e)
                self.stream = None
        return self._start_external()

    def _start_external(self):
        wavp = os.path.join(tempfile.gettempdir(), "hqrip_play_%d.wav" % os.getpid())
        write_wav(wavp, np.clip(self.app.project.render(self.pos), -1, 1))
        started = False
        if sys.platform.startswith('win'):
            try:
                import winsound
                winsound.PlaySound(wavp, winsound.SND_FILENAME | winsound.SND_ASYNC)
                started = True
                self.proc = None
            except Exception:
                pass
        else:
            for c in (['afplay'], ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet'],
                      ['paplay'], ['aplay', '-q']):
                if shutil.which(c[0]):
                    self.proc = subprocess.Popen(c + [wavp], stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL)
                    started = True
                    break
        if not started:
            self.app.status("No audio output found. Try: pip install sounddevice")
            return False
        self.t0, self.p0, self.playing, self.mode = time.time(), self.pos, True, 'ext'
        return True

    def stop(self):
        if self.mode == 'ext':
            self.pos = self.position()
        if self.stream is not None:
            try: self.stream.stop(); self.stream.close()
            except Exception: pass
            self.stream = None
        if self.proc is not None:
            try: self.proc.terminate()
            except Exception: pass
            self.proc = None
        if self.mode == 'ext' and sys.platform.startswith('win'):
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        self.playing, self.mode, self.peak = False, None, 0.0


# ---------------------------------------------------------------------------
# Themed widgets (Label-based buttons render identically on every OS)
# ---------------------------------------------------------------------------
if tk is not None:
    class Btn(tk.Label):
        def __init__(self, master, text='', command=None, state='normal', **kw):
            self._cmd, self._state = command, state
            self._abg = kw.pop('activebackground', None)
            self._afg = kw.pop('activeforeground', None)
            self._dfg = kw.pop('disabledforeground', '#9aa7b5')
            self._b_bg, self._b_fg = kw.get('bg', '#1e6fbf'), kw.get('fg', '#ffffff')
            kw.setdefault('bg', self._b_bg); kw.setdefault('fg', self._b_fg)
            kw.setdefault('relief', 'raised'); kw.setdefault('bd', 1)
            super().__init__(master, text=text, **kw)
            self.bind('<Enter>', lambda e: self._refresh(True))
            self.bind('<Leave>', lambda e: self._refresh(False))
            self.bind('<ButtonPress-1>', self._press)
            self.bind('<ButtonRelease-1>', self._release)
            self._refresh()

        def _refresh(self, hover=False):
            try:
                on = self._state != 'disabled'
                bg = self._abg if (on and hover and self._abg) else self._b_bg
                fg = self._b_fg if on else self._dfg
                tk.Label.configure(self, bg=bg, fg=fg, cursor='hand2' if on else 'arrow')
            except tk.TclError:
                pass

        def _press(self, e):
            if self._state != 'disabled':
                tk.Label.configure(self, relief='sunken')

        def _release(self, e):
            try:
                tk.Label.configure(self, relief='raised')
                inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
                if self._state != 'disabled' and inside and self._cmd:
                    self._cmd()
            except tk.TclError:
                pass

        def configure(self, cnf=None, **kw):
            if cnf: kw.update(cnf)
            if 'command' in kw: self._cmd = kw.pop('command')
            if 'state' in kw: self._state = kw.pop('state')
            for k, a in (('activebackground', '_abg'), ('activeforeground', '_afg'),
                         ('disabledforeground', '_dfg')):
                if k in kw: setattr(self, a, kw.pop(k))
            for k in ('bg', 'background'):
                if k in kw: self._b_bg = kw.pop(k)
            for k in ('fg', 'foreground'):
                if k in kw: self._b_fg = kw.pop(k)
            if kw: tk.Label.configure(self, **kw)
            self._refresh()
        config = configure

    class RadioText(tk.Label):
        def __init__(self, master, text='', value=None, variable=None, command=None, **kw):
            self._txt, self._value, self._var, self._cmd = text, value, variable, command
            kw.setdefault('cursor', 'hand2')
            super().__init__(master, **kw)
            variable.trace_add('write', lambda *a: self._sync())
            self.bind('<Button-1>', self._click)
            self._sync()

        def _sync(self):
            try: tk.Label.configure(self, text=('(o) ' if self._var.get() == self._value else '( ) ') + self._txt)
            except tk.TclError: pass

        def _click(self, e):
            self._var.set(self._value)
            if self._cmd: self._cmd()

# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------
HDR_W, RULER_H, LANE_H = 176, 26, 74


class Ctx:
    """Handed to background jobs: thread-safe log + progress."""
    def __init__(self, app): self.app = app
    def log(self, m): self.app.log(m)
    def prog(self, v): self.app.post(lambda: self.app.set_prog(v))


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP)
        self.root.geometry("1200x780")
        self.root.minsize(920, 620)
        self.project = Project()
        self.player = Player(self)
        self.q = queue.Queue()
        self.log_buf, self._log_widget = [], None
        self.theme = tk.StringVar(value='dark')
        self.status_text = tk.StringVar(value="Ready | files = off | drag clips, Space = play")
        self.prog_v = tk.DoubleVar(value=0)
        self.bpm_v = tk.StringVar(value="120")
        self.loop_v = tk.BooleanVar(value=False)
        self.snap_v = tk.BooleanVar(value=True)
        self.fade_v = tk.BooleanVar(value=True)
        self.master_v = tk.DoubleVar(value=90)
        self.zoom, self.sx, self.sy = 40.0, 0.0, 0.0
        self.sel, self.undo, self.redo = None, [], []
        self.play_from, self.drag, self._ins_lock = 0, None, False
        self._proc_after = None
        self.dest = os.path.join(os.path.expanduser("~"), "HQRipper_Output")
        self.build_menu()
        self.build_ui()
        self.bind_keys()
        self.apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(40, self._pump)
        self.root.after(33, self._tick)

    # ---- helpers ---------------------------------------------------------
    def t(self): return THEMES[self.theme.get()]

    def post(self, fn): self.q.put(fn)

    def _pump(self):
        try:
            while True:
                fn = self.q.get_nowait()
                try: fn()
                except Exception as e: self._log_ui("[UI error] %r" % e)
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    def log(self, m): self.post(lambda: self._log_ui(m))

    def _log_ui(self, m):
        self.log_buf.append(m)
        w = self._log_widget
        if w is not None:
            try:
                w.insert('end', m + '\n'); w.see('end')
            except tk.TclError:
                self._log_widget = None

    def status(self, m):
        self.status_text.set(m)

    def set_prog(self, v):
        self.prog_v.set(v)

    def run_bg(self, title, fn, on_done=None):
        ctx = Ctx(self)
        self.status(title + " ...")
        self.prog_v.set(2)

        def work():
            try:
                res = fn(ctx)
                self.post(lambda: self._job_done(title, res, on_done, None))
            except Exception as e:
                ctx.log("[ERROR] %s" % e)
                self.post(lambda e=e: self._job_done(title, None, None, e))
        threading.Thread(target=work, daemon=True).start()

    def _job_done(self, title, res, on_done, err):
        self.prog_v.set(0)
        if err is not None:
            self.status("Error | %s" % err)
            messagebox.showerror(APP, str(err))
            return
        self.status(title + " done")
        if on_done: on_done(res)

    # ---- menu ------------------------------------------------------------
    def build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        self.root.config(menu=m)
        f = tk.Menu(m, tearoff=0); m.add_cascade(label="File", menu=f)
        f.add_command(label="Add Track from URL...   Ctrl+U", command=self.add_url_dialog)
        f.add_command(label="Paste URL as Track", command=self.paste_url_track)
        f.add_command(label="Open Audio File...  (files = off)", state='disabled')
        f.add_separator()
        f.add_command(label="Export Mixdown...   Ctrl+E", command=self.export_dialog)
        f.add_separator()
        f.add_command(label="Exit", command=self.quit)
        e = tk.Menu(m, tearoff=0); m.add_cascade(label="Edit", menu=e)
        e.add_command(label="Undo   Ctrl+Z", command=self.undo_cmd)
        e.add_command(label="Redo   Ctrl+Y", command=self.redo_cmd)
        e.add_separator()
        e.add_command(label="Duplicate Track   Ctrl+D", command=self.duplicate_track)
        e.add_command(label="Delete Track   Del", command=self.delete_track)
        tr = tk.Menu(m, tearoff=0); m.add_cascade(label="Track", menu=tr)
        tr.add_command(label="Add Synth Drums", command=lambda: self.add_synth('drums'))
        tr.add_command(label="Add Synth Bass", command=lambda: self.add_synth('bass'))
        tr.add_command(label="Add Synth Pad", command=lambda: self.add_synth('pad'))
        tr.add_separator()
        tr.add_command(label="Re-detect BPM / Key", command=self.redetect)
        tr.add_command(label="Sync ALL Tracks to Master BPM", command=self.sync_all)
        tr.add_command(label="Set Master BPM from Selected Track", command=self.bpm_from_sel)
        r = tk.Menu(m, tearoff=0); m.add_cascade(label="Rip", menu=r)
        r.add_command(label="HQ Rip Builder...   Ctrl+R", command=self.rip_dialog)
        v = tk.Menu(m, tearoff=0); m.add_cascade(label="View", menu=v)
        for k in THEME_ORDER:
            v.add_radiobutton(label=THEME_LABELS[k], value=k, variable=self.theme, command=self.set_theme)
        v.add_separator()
        v.add_command(label="Zoom In   Ctrl+=", command=lambda: self.set_zoom(self.zoom * 1.4))
        v.add_command(label="Zoom Out  Ctrl+-", command=lambda: self.set_zoom(self.zoom / 1.4))
        v.add_command(label="Zoom to Fit", command=self.zoom_fit)
        v.add_separator()
        v.add_checkbutton(label="Snap to Beat", variable=self.snap_v)
        v.add_checkbutton(label="Fade-out on Export", variable=self.fade_v)
        v.add_command(label="Show Log", command=self.show_log)
        h = tk.Menu(m, tearoff=0); m.add_cascade(label="Help", menu=h)
        h.add_command(label="Patch Notes", command=self.show_patch_notes)
        h.add_command(label="About Copyright...", command=lambda: messagebox.showinfo(APP, COPYRIGHT_TEXT))
        h.add_command(label="About", command=self.show_about)

    # ---- UI --------------------------------------------------------------
    def build_ui(self):
        r = self.root
        self.banner = tk.Frame(r, height=34); self.banner.pack(fill='x'); self.banner.pack_propagate(False)
        self.banner_title = tk.Label(self.banner, text="  ac's hqripper 0.2", font=('Segoe UI', 13, 'bold'), anchor='w')
        self.banner_title.pack(side='left', fill='y')
        self.banner_sub = tk.Label(self.banner, text="High Quality Rip DAW   files = off   ", font=('Segoe UI', 8))
        self.banner_sub.pack(side='right', fill='y')

        # transport bar
        tb = tk.Frame(r, bd=1, relief='groove'); tb.pack(fill='x'); self.transport = tb
        def add(text, cmd, w=4):
            b = Btn(tb, text=text, command=cmd, width=w, font=('Segoe UI', 10, 'bold'), padx=4)
            b.pack(side='left', padx=2, pady=4); return b
        add("|<", self.to_start); self.play_btn = add(">", self.toggle_play); add("[]", self.stop_cmd)
        self.time_lbl = tk.Label(tb, text="00:00.00   1.1", font=('Consolas', 13, 'bold'), width=16)
        self.time_lbl.pack(side='left', padx=8)
        tk.Label(tb, text="BPM").pack(side='left')
        self.bpm_e = tk.Entry(tb, textvariable=self.bpm_v, width=6, justify='center')
        self.bpm_e.pack(side='left', padx=3)
        self.bpm_e.bind('<Return>', lambda e: self.bpm_commit()); self.bpm_e.bind('<FocusOut>', lambda e: self.bpm_commit())
        tk.Checkbutton(tb, text="Loop", variable=self.loop_v, command=lambda: setattr(self.player, 'loop', self.loop_v.get())).pack(side='left', padx=4)
        tk.Checkbutton(tb, text="Snap", variable=self.snap_v).pack(side='left')
        Btn(tb, text="+ URL", command=self.add_url_dialog, padx=6).pack(side='left', padx=(12, 2))
        Btn(tb, text="+ Drums", command=lambda: self.add_synth('drums'), padx=6).pack(side='left', padx=2)
        Btn(tb, text="HQ Rip", command=self.rip_dialog, padx=8).pack(side='left', padx=2)
        Btn(tb, text="Export", command=self.export_dialog, padx=8).pack(side='left', padx=2)
        Btn(tb, text="Theme", command=self.cycle_theme, padx=6).pack(side='left', padx=2)
        self.meter = tk.Canvas(tb, width=90, height=12, highlightthickness=1); self.meter.pack(side='right', padx=8)
        tk.Label(tb, text="Master").pack(side='right')
        ms = tk.Scale(tb, from_=0, to=150, orient='horizontal', variable=self.master_v, showvalue=False,
                      length=90, command=lambda v: setattr(self.project, 'master', float(v) / 100),
                      highlightthickness=0, sliderlength=14)
        ms.pack(side='right', padx=4)
        self.zoom_s = tk.Scale(tb, from_=4, to=300, orient='horizontal', showvalue=False, length=90,
                               command=lambda v: self.set_zoom(float(v), from_slider=True),
                               highlightthickness=0, sliderlength=14)
        self.zoom_s.set(self.zoom); self.zoom_s.pack(side='right', padx=4)
        tk.Label(tb, text="Zoom").pack(side='right')

        # status + progress (bottom)
        self.statusbar = tk.Label(r, textvariable=self.status_text, anchor='w', font=('Segoe UI', 8),
                                  relief='sunken', bd=1, padx=6)
        self.statusbar.pack(side='bottom', fill='x')
        self.prog_bar = ttk.Progressbar(r, variable=self.prog_v, maximum=100)
        self.prog_bar.pack(side='bottom', fill='x')

        # bottom inspector / log
        self.nb = ttk.Notebook(r, height=190); self.nb.pack(side='bottom', fill='x')
        self.ins = tk.Frame(self.nb); self.nb.add(self.ins, text=" Inspector ")
        logf = tk.Frame(self.nb); self.nb.add(logf, text=" Log ")
        self.log_txt = scrolledtext.ScrolledText(logf, height=8, font=('Consolas', 9))
        self.log_txt.pack(fill='both', expand=True)
        self._log_widget = self.log_txt
        self.log_txt.insert('1.0', "\n".join(self.log_buf) + ("\n" if self.log_buf else ""))
        self._build_inspector()

        # timeline
        mid = tk.Frame(r); mid.pack(fill='both', expand=True)
        self.cv = tk.Canvas(mid, highlightthickness=0)
        self.vbar = ttk.Scrollbar(mid, orient='vertical', command=self._vscroll)
        self.hbar = ttk.Scrollbar(mid, orient='horizontal', command=self._hscroll)
        self.vbar.pack(side='right', fill='y'); self.hbar.pack(side='bottom', fill='x')
        self.cv.pack(fill='both', expand=True)
        cv = self.cv
        cv.bind('<Configure>', lambda e: self.redraw())
        cv.bind('<ButtonPress-1>', self._down); cv.bind('<B1-Motion>', self._move)
        cv.bind('<ButtonRelease-1>', self._up)
        cv.bind('<MouseWheel>', self._wheel)
        cv.bind('<Button-4>', lambda e: self._wheel(e, 1)); cv.bind('<Button-5>', lambda e: self._wheel(e, -1))

    def _build_inspector(self):
        f = self.ins
        self.v_name, self.v_start = tk.StringVar(), tk.StringVar(value="0.0")
        self.v_vol, self.v_pan = tk.DoubleVar(value=100), tk.DoubleVar(value=0)
        self.v_pitch, self.v_sync = tk.StringVar(value="0"), tk.BooleanVar(value=False)
        self.v_eq = [tk.DoubleVar(value=100) for _ in range(3)]
        self.info_lbl = tk.Label(f, text="No track selected", anchor='w')

        def L(txt, r, c): tk.Label(f, text=txt, anchor='e').grid(row=r, column=c, sticky='e', padx=(10, 2), pady=3)
        def S(var, lo, hi, r, c, cb, key):
            s = tk.Scale(f, from_=lo, to=hi, orient='horizontal', variable=var, showvalue=True, length=150,
                         highlightthickness=0, sliderlength=14, command=lambda v: cb(key))
            s.grid(row=r, column=c, padx=2); s.bind('<ButtonPress-1>', lambda e: self.push_undo()); return s
        L("Name", 0, 0)
        ne = tk.Entry(f, textvariable=self.v_name, width=22); ne.grid(row=0, column=1, columnspan=2, sticky='w')
        ne.bind('<Return>', lambda e: self._ins_changed('name')); ne.bind('<FocusOut>', lambda e: self._ins_changed('name'))
        L("Start (s)", 0, 3)
        se = tk.Spinbox(f, from_=0, to=3600, increment=0.25, textvariable=self.v_start, width=8,
                        command=lambda: self._ins_changed('start')); se.grid(row=0, column=4, sticky='w')
        se.bind('<Return>', lambda e: self._ins_changed('start'))
        L("Volume %", 1, 0); S(self.v_vol, 0, 150, 1, 1, self._ins_changed, 'vol')
        L("Pan L-R", 1, 3); S(self.v_pan, -100, 100, 1, 4, self._ins_changed, 'pan')
        L("EQ Low", 2, 0); S(self.v_eq[0], 0, 200, 2, 1, self._ins_changed, 'eq')
        L("Mid", 2, 3); S(self.v_eq[1], 0, 200, 2, 4, self._ins_changed, 'eq')
        L("High", 2, 5); S(self.v_eq[2], 0, 200, 2, 6, self._ins_changed, 'eq')
        L("Pitch (st)", 0, 5)
        pe = tk.Spinbox(f, from_=-12, to=12, textvariable=self.v_pitch, width=5,
                        command=lambda: self._ins_changed('pitch')); pe.grid(row=0, column=6, sticky='w')
        pe.bind('<Return>', lambda e: self._ins_changed('pitch'))
        tk.Checkbutton(f, text="Sync to master BPM", variable=self.v_sync,
                       command=lambda: self._ins_changed('sync')).grid(row=1, column=5, columnspan=2, sticky='w', padx=8)
        self.info_lbl.grid(row=3, column=0, columnspan=5, sticky='w', padx=10)
        bf = tk.Frame(f); bf.grid(row=3, column=5, columnspan=3, sticky='e')
        Btn(bf, text="Re-detect", command=self.redetect, padx=6).pack(side='left', padx=2)
        Btn(bf, text="Duplicate", command=self.duplicate_track, padx=6).pack(side='left', padx=2)
        Btn(bf, text="Delete", command=self.delete_track, padx=6).pack(side='left', padx=2)

    def bind_keys(self):
        r = self.root
        def guarded(fn):
            def h(e=None):
                if self.root.focus_get().winfo_class() in ('Entry', 'Spinbox', 'Text', 'TCombobox'):
                    return
                fn(); return 'break'
            return h
        r.bind('<space>', guarded(self.toggle_play)); r.bind('<Home>', guarded(self.to_start))
        r.bind('<Delete>', guarded(self.delete_track))
        r.bind('<Control-z>', lambda e: self.undo_cmd()); r.bind('<Control-y>', lambda e: self.redo_cmd())
        r.bind('<Control-Z>', lambda e: self.redo_cmd())
        r.bind('<Control-d>', lambda e: self.duplicate_track()); r.bind('<Control-e>', lambda e: self.export_dialog())
        r.bind('<Control-u>', lambda e: self.add_url_dialog()); r.bind('<Control-r>', lambda e: self.rip_dialog())
        r.bind('<Control-equal>', lambda e: self.set_zoom(self.zoom * 1.4))
        r.bind('<Control-minus>', lambda e: self.set_zoom(self.zoom / 1.4))
        r.bind('<Control-v>', lambda e: None if self.root.focus_get().winfo_class() in ('Entry', 'Spinbox', 'Text') else self.paste_url_track())

    # ---- coordinates / scrolling ----------------------------------------
    def _lane_y(self, i): return RULER_H + i * LANE_H - self.sy
    def _t2x(self, t): return HDR_W + t * self.zoom - self.sx
    def _x2t(self, x): return max(0.0, (x - HDR_W + self.sx) / self.zoom)

    def _total_w(self):
        return (self.project.length_samples() / SR + 40) * self.zoom

    def _clamp_scroll(self):
        W, H = max(1, self.cv.winfo_width()), max(1, self.cv.winfo_height())
        tw, th = self._total_w(), RULER_H + len(self.project.tracks) * LANE_H + 10
        self.sx = max(0.0, min(self.sx, max(0.0, tw - (W - HDR_W))))
        self.sy = max(0.0, min(self.sy, max(0.0, th - H)))
        self.hbar.set(self.sx / tw, min(1.0, (self.sx + W - HDR_W) / tw))
        self.vbar.set(self.sy / th, min(1.0, (self.sy + H) / th))

    def _hscroll(self, *a):
        vis = max(1, self.cv.winfo_width() - HDR_W)
        if a[0] == 'moveto': self.sx = float(a[1]) * self._total_w()
        else: self.sx += int(a[1]) * (vis * 0.1 if a[2] == 'units' else vis * 0.9)
        self.redraw()

    def _vscroll(self, *a):
        H = max(1, self.cv.winfo_height())
        th = RULER_H + len(self.project.tracks) * LANE_H + 10
        if a[0] == 'moveto': self.sy = float(a[1]) * th
        else: self.sy += int(a[1]) * (LANE_H / 2 if a[2] == 'units' else H * 0.9)
        self.redraw()

    def _wheel(self, e, d=None):
        if d is None: d = 1 if e.delta > 0 else -1
        if e.state & 0x4: self.set_zoom(self.zoom * (1.2 if d > 0 else 1 / 1.2))
        elif e.state & 0x1: self.sx -= d * 120; self.redraw()
        else: self.sy -= d * 40; self.redraw()

    def set_zoom(self, z, from_slider=False):
        z = max(4.0, min(300.0, z))
        cur = self.player.position() / SR
        px = self._t2x(cur)
        self.zoom = z
        if not from_slider: self.zoom_s.set(z)
        self.sx = max(0.0, cur * z - (px - HDR_W)) if HDR_W <= px <= self.cv.winfo_width() else self.sx
        self.redraw()

    def zoom_fit(self):
        L = self.project.length_samples() / SR
        if L > 0:
            self.sx = 0
            self.set_zoom((self.cv.winfo_width() - HDR_W - 30) / (L + 1))

    # ---- drawing ---------------------------------------------------------
    def redraw(self):
        cv = self.cv
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 60 or H < 40: return
        self._clamp_scroll()
        th = self.t()
        cv.delete('all'); cv.configure(bg=th['lane1'])
        tracks = self.project.tracks
        beat = 60.0 / self.project.bpm * self.zoom
        # lanes
        for i, t in enumerate(tracks):
            y0 = self._lane_y(i)
            if y0 > H or y0 + LANE_H < RULER_H: continue
            cv.create_rectangle(HDR_W, y0, W, y0 + LANE_H, fill=th['lane2'] if i % 2 else th['lane1'], outline=th['grid'])
        # grid
        every = 1 if beat >= 14 else (4 if beat * 4 >= 14 else 16)
        b0, b1 = int(self.sx / beat) // every * every, int((self.sx + W - HDR_W) / beat) + 1
        ybot = min(H, RULER_H + len(tracks) * LANE_H - self.sy)
        for b in range(b0, b1 + 1, every):
            x = HDR_W + b * beat - self.sx
            if x < HDR_W: continue
            cv.create_line(x, RULER_H, x, max(ybot, RULER_H), fill=th['bar'] if b % 4 == 0 else th['grid'])
        # clips
        for i, t in enumerate(tracks):
            y0 = self._lane_y(i)
            if y0 > H or y0 + LANE_H < RULER_H: continue
            x0 = self._t2x(t.start)
            x1 = x0 + len(t.proc) / SR * self.zoom
            xa, xb = max(x0, HDR_W), min(x1, W)
            if xb <= xa: continue
            dim = t.mute or (any(o.solo for o in tracks) and not t.solo)
            col = '#555555' if dim else t.color
            cv.create_rectangle(xa, y0 + 4, xb, y0 + LANE_H - 4, fill=th['panel'],
                                outline=th['fg'] if t is self.sel else col, width=2 if t is self.sel else 1)
            mid, hh = y0 + LANE_H / 2, LANE_H / 2 - 8
            cols = np.arange(int(xa), int(xb) + 1)
            s0 = np.maximum(0, ((cols - x0) / self.zoom * SR / PK).astype(int))
            s1 = np.maximum(s0 + 1, ((cols + 1 - x0) / self.zoom * SR / PK).astype(int))
            pk, n = t.peaks, len(t.peaks)
            for x, a, b in zip(cols, s0, s1):
                if a >= n: break
                v = float(pk[a:b].max()) if b > a and a < n else 0.0
                h = max(1.0, min(1.0, v) * hh)
                cv.create_line(x, mid - h, x, mid + h, fill=col)
            cv.create_text(xa + 6, y0 + 10, text=t.name[:40], anchor='w', fill=th['fg'], font=('Segoe UI', 8, 'bold'))
        if not tracks:
            cv.create_text(HDR_W + (W - HDR_W) / 2, RULER_H + 90, fill=th['muted'], font=('Segoe UI', 12),
                           text="Empty project.\nAdd a track: + URL (paste a YouTube link) or Track > Add Synth Drums.\n"
                                "Then HQ Rip to mash two tracks together.", justify='center')
        # headers
        for i, t in enumerate(tracks):
            y0 = self._lane_y(i)
            if y0 > H or y0 + LANE_H < RULER_H: continue
            cv.create_rectangle(0, y0, HDR_W, y0 + LANE_H, fill=th['hdr_sel'] if t is self.sel else th['hdr'], outline=th['grid'])
            cv.create_rectangle(0, y0, 5, y0 + LANE_H, fill=t.color, outline=t.color)
            cv.create_text(12, y0 + 16, text="%d  %s" % (i + 1, t.name[:12]), anchor='w', fill=th['fg'], font=('Segoe UI', 9, 'bold'))
            cv.create_text(12, y0 + 40, text="vol %d%%  pan %s" % (t.vol * 100, 'C' if abs(t.pan) < .02 else ('L%d' % (-t.pan * 100) if t.pan < 0 else 'R%d' % (t.pan * 100))),
                           anchor='w', fill=th['muted'], font=('Segoe UI', 8))
            info = "%s BPM  %s%s" % ("%.0f" % t.bpm if t.bpm else "--", key_name(t.key) if t.key else "--", "  *sync" if t.sync else "")
            cv.create_text(12, y0 + 58, text=info, anchor='w', fill=th['muted'], font=('Segoe UI', 8))
            (ma, mb, mc, md), (sa, sb, sc, sd_) = self._ms_rects(i)
            cv.create_rectangle(ma, mb, mc, md, fill='#d9a400' if t.mute else th['btn'], outline='')
            cv.create_text((ma + mc) / 2, (mb + md) / 2, text="M", fill='#ffffff', font=('Segoe UI', 8, 'bold'))
            cv.create_rectangle(sa, sb, sc, sd_, fill='#2fb463' if t.solo else th['btn'], outline='')
            cv.create_text((sa + sc) / 2, (sb + sd_) / 2, text="S", fill='#ffffff', font=('Segoe UI', 8, 'bold'))
        # ruler
        cv.create_rectangle(0, 0, W, RULER_H, fill=th['toolbar'], outline=th['grid'])
        cv.create_text(8, RULER_H / 2, text="TRACKS", anchor='w', fill=th['muted'], font=('Segoe UI', 8, 'bold'))
        bar_px = beat * 4
        lab_every = 1 if bar_px >= 40 else (2 if bar_px >= 20 else (4 if bar_px >= 10 else 16))
        for b in range(b0 // 4 * 4, b1 + 1, 4):
            x = HDR_W + b * beat - self.sx
            if x < HDR_W: continue
            cv.create_line(x, RULER_H - 8, x, RULER_H, fill=th['muted'])
            if (b // 4) % lab_every == 0:
                cv.create_text(x + 3, 10, text=str(b // 4 + 1), anchor='w', fill=th['fg'], font=('Segoe UI', 8))
        self._draw_playhead()

    def _ms_rects(self, i):
        y0 = self._lane_y(i)
        return (HDR_W - 62, y0 + 8, HDR_W - 38, y0 + 26), (HDR_W - 34, y0 + 8, HDR_W - 10, y0 + 26)

    def _draw_playhead(self):
        cv = self.cv
        cv.delete('ph')
        x = self._t2x(self.player.position() / SR)
        if x >= HDR_W:
            cv.create_line(x, 0, x, cv.winfo_height(), fill='#ff4d4d', width=2, tags='ph')
            cv.create_polygon(x - 6, 0, x + 6, 0, x, 10, fill='#ff4d4d', outline='', tags='ph')

    # ---- mouse -----------------------------------------------------------
    def _lane_at(self, y):
        if y < RULER_H: return None
        i = int((y - RULER_H + self.sy) // LANE_H)
        return i if 0 <= i < len(self.project.tracks) else None

    def _down(self, e):
        self.cv.focus_set()
        if e.y < RULER_H and e.x >= HDR_W:
            self.drag = ('seek',); self._seek_x(e.x); return
        i = self._lane_at(e.y)
        if i is None:
            return
        t = self.project.tracks[i]
        self.select(t)
        if e.x < HDR_W:
            (ma, mb, mc, md), (sa, sb, sc, sd_) = self._ms_rects(i)
            if ma <= e.x <= mc and mb <= e.y <= md:
                self.push_undo(); t.mute = not t.mute; self.redraw(); self._load_inspector()
            elif sa <= e.x <= sc and sb <= e.y <= sd_:
                self.push_undo(); t.solo = not t.solo; self.redraw()
            return
        x0 = self._t2x(t.start); x1 = x0 + len(t.proc) / SR * self.zoom
        if x0 <= e.x <= x1:
            self.push_undo()
            self.drag = ('clip', t, self._x2t(e.x) - t.start, t.start)

    def _move(self, e):
        if not self.drag: return
        if self.drag[0] == 'seek': self._seek_x(e.x)
        elif self.drag[0] == 'clip':
            _, t, off, _s = self.drag
            ns = max(0.0, self._x2t(e.x) - off)
            if self.snap_v.get():
                b = 60.0 / self.project.bpm
                ns = round(ns / b) * b
            t.start = ns
            self.v_start.set("%.2f" % ns)
            self.redraw()

    def _up(self, e):
        d, self.drag = self.drag, None
        if d and d[0] == 'clip' and abs(d[1].start - d[3]) < 1e-6 and self.undo:
            self.undo.pop()                            # nothing moved -> drop the snapshot

    def _seek_x(self, x):
        self.player.pos = int(self._x2t(x) * SR)
        if self.player.mode == 'ext' and self.player.playing:
            self.player.stop(); self.player.start()
        self.play_from = self.player.pos
        self._update_time(); self._draw_playhead()

    # ---- transport ------------------------------------------------------
    def to_start(self):
        was = self.player.playing
        if was: self.player.stop()
        self.player.pos = self.play_from = 0
        self.sx = 0
        if was: self.player.start()
        self.redraw(); self._update_time()

    def toggle_play(self):
        p = self.player
        if p.playing:
            p.stop(); self.play_btn.configure(text=">"); self.status("Paused")
            return
        if self.project.length_samples() == 0:
            self.status("Nothing to play. Add a track first."); return
        if p.pos >= self.project.length_samples(): p.pos = 0
        self.play_from = p.pos
        if p.start():
            self.play_btn.configure(text="||"); self.status("Playing")

    def stop_cmd(self):
        p = self.player
        if p.playing:
            p.stop(); p.pos = self.play_from
        else:
            p.pos = self.play_from = 0
        self.play_btn.configure(text=">"); self.redraw(); self._update_time()

    def _update_time(self):
        s = self.player.position() / SR
        beat = s / (60.0 / self.project.bpm)
        self.time_lbl.configure(text="%02d:%05.2f   %d.%d" % (int(s // 60), s % 60, int(beat // 4) + 1, int(beat % 4) + 1))

    def _tick(self):
        try:
            p = self.player
            if p.playing:
                if p.ended:
                    p.stop(); p.pos = self.play_from; p.ended = False
                    self.play_btn.configure(text=">"); self.status("Ready")
                    self.redraw()
                else:
                    x = self._t2x(p.position() / SR)
                    W = self.cv.winfo_width()
                    if x > W - 30 or x < HDR_W - 1:
                        self.sx = max(0.0, p.position() / SR * self.zoom - 40); self.redraw()
                    else:
                        self._draw_playhead()
                    self._update_time()
            self.meter.delete('all')
            w = int(min(1.0, p.peak) * 88)
            self.meter.create_rectangle(1, 1, w, 11, fill='#2fb463' if p.peak < .9 else '#ff4d4d', outline='')
            p.peak *= 0.85
        except tk.TclError:
            return
        self.root.after(33, self._tick)

    def bpm_commit(self):
        try:
            b = max(40.0, min(240.0, float(self.bpm_v.get())))
        except ValueError:
            b = self.project.bpm
        self.bpm_v.set(("%.2f" % b).rstrip('0').rstrip('.'))
        if abs(b - self.project.bpm) > 1e-6:
            self.project.bpm = b
            for t in self.project.tracks: self.ensure_proc(t)
            self.redraw()

    # ---- undo ------------------------------------------------------------
    def _snap(self): return ([(t, t.params()) for t in self.project.tracks], self.project.bpm)

    def push_undo(self):
        self.undo.append(self._snap()); self.redo.clear()
        del self.undo[:-100]

    def _restore(self, s):
        lst, bpm = s
        self.project.tracks[:] = [t for t, _ in lst]
        self.project.bpm = bpm; self.bpm_v.set("%g" % bpm)
        for t, p in lst:
            t.apply(p); self.ensure_proc(t)
        if self.sel not in self.project.tracks: self.sel = None
        self.redraw(); self._load_inspector()

    def undo_cmd(self):
        if self.undo:
            self.redo.append(self._snap()); self._restore(self.undo.pop()); self.status("Undo")

    def redo_cmd(self):
        if self.redo:
            self.undo.append(self._snap()); self._restore(self.redo.pop()); self.status("Redo")

    # ---- tracks ----------------------------------------------------------
    def select(self, t):
        self.sel = t
        self._load_inspector(); self.redraw()

    def add_track(self, t, undoable=True):
        if undoable: self.push_undo()
        if not self.project.tracks and t.bpm:
            self.project.bpm = float(round(t.bpm)); self.bpm_v.set("%g" % self.project.bpm)
            self.log("[project] master BPM = %g (from first track)" % self.project.bpm)
        self.project.tracks.append(t)
        self.sel = t
        self.ensure_proc(t)
        self._load_inspector()
        if len(self.project.tracks) == 1: self.zoom_fit()
        self.redraw()

    def add_synth(self, kind):
        bpm = self.project.bpm
        fn = {'drums': synth_drums, 'bass': synth_bass, 'pad': synth_pad}[kind]
        t = Track("Synth %s %g" % (kind, bpm), fn(bpm))
        t.bpm = bpm if kind != 'pad' else bpm
        t.key = (9, True) if kind != 'drums' else None
        self.add_track(t)
        self.status("Added synth %s" % kind)

    def duplicate_track(self):
        if self.sel:
            self.push_undo()
            d = self.sel.duplicate()
            self.project.tracks.insert(self.project.tracks.index(self.sel) + 1, d)
            self.select(d)

    def delete_track(self):
        if self.sel and self.sel in self.project.tracks:
            self.push_undo()
            self.project.tracks.remove(self.sel)
            self.sel = None
            self._load_inspector(); self.redraw()

    def redetect(self):
        t = self.sel
        if not t: return
        def job(ctx):
            ctx.log("[analyze] %s" % t.name)
            return detect_bpm(t.audio), detect_key(t.audio)
        def done(r):
            t.bpm, t.key = r
            self.log("  -> %s BPM, %s" % (r[0] and "%.1f" % r[0], key_name(r[1])))
            self._load_inspector(); self.redraw()
        self.run_bg("Analyzing", job, done)

    def sync_all(self):
        self.push_undo()
        for t in self.project.tracks:
            if t.bpm: t.sync = True; self.ensure_proc(t)
        self._load_inspector(); self.redraw()

    def bpm_from_sel(self):
        if self.sel and self.sel.bpm:
            self.bpm_v.set("%g" % round(self.sel.bpm)); self.bpm_commit()

    # ---- inspector -------------------------------------------------------
    def _load_inspector(self):
        t = self.sel
        self._ins_lock = True
        try:
            if t is None:
                self.info_lbl.configure(text="No track selected  |  click a clip or track header")
                self.v_name.set("")
                return
            self.v_name.set(t.name); self.v_start.set("%.2f" % t.start)
            self.v_vol.set(t.vol * 100); self.v_pan.set(t.pan * 100)
            self.v_pitch.set(str(t.pitch)); self.v_sync.set(t.sync)
            for v, e in zip(self.v_eq, t.eq): v.set(e * 100)
            self.info_lbl.configure(text="%s  |  %.1fs  |  BPM %s  |  Key %s%s" % (
                t.name[:30], len(t.audio) / SR, "%.1f" % t.bpm if t.bpm else "--",
                key_name(t.key) if t.key else "--", "  |  processing..." if t.busy else ""))
        finally:
            self._ins_lock = False

    def _ins_changed(self, key):
        t = self.sel
        if t is None or self._ins_lock: return
        try:
            if key == 'name': t.name = self.v_name.get().strip() or t.name
            elif key == 'start': t.start = max(0.0, float(self.v_start.get()))
            elif key == 'vol': t.vol = self.v_vol.get() / 100
            elif key == 'pan': t.pan = self.v_pan.get() / 100
            elif key == 'eq': t.eq = [v.get() / 100 for v in self.v_eq]
            elif key == 'pitch': self.push_undo(); t.pitch = max(-12, min(12, int(float(self.v_pitch.get()))))
            elif key == 'sync': self.push_undo(); t.sync = bool(self.v_sync.get())
        except ValueError:
            return
        if key in ('eq', 'pitch', 'sync'):
            self._debounce_proc(t)
        self.redraw()

    def _debounce_proc(self, t):
        if self._proc_after: self.root.after_cancel(self._proc_after)
        self._proc_after = self.root.after(300, lambda: self.ensure_proc(t))

    def ensure_proc(self, t):
        if t.busy or t.proc_key == t.want_key(self.project.bpm):
            return
        t.busy = True
        bpm, want = self.project.bpm, t.want_key(self.project.bpm)
        if t is self.sel: self._load_inspector()

        def work():
            try:
                y = t.build(bpm)
                pk = compute_peaks(y)
                self.post(lambda: self._proc_done(t, y, pk, want))
            except Exception as e:
                self.log("[process error] %s" % e)
                self.post(lambda: setattr(t, 'busy', False))
        threading.Thread(target=work, daemon=True).start()

    def _proc_done(self, t, y, pk, want):
        t.proc, t.peaks, t.proc_key, t.busy = y, pk, want, False
        if t.proc_key != t.want_key(self.project.bpm): self.ensure_proc(t)
        if t is self.sel: self._load_inspector()
        self.redraw()

    # ---- URL tracks ------------------------------------------------------
    def _fetch_track(self, url, ctx):
        tmp = tempfile.mkdtemp(prefix="hqrip_")
        try:
            path, title = fetch_url(url, tmp, ctx.log)
            ctx.prog(40); ctx.log("[load] decoding ...")
            y = load_audio(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        ctx.log("[analyze] BPM + key ...")
        t = Track(title[:60], y, source=url)
        t.bpm, t.key = detect_bpm(y), detect_key(y)
        ctx.log("  %s: %s BPM, %s" % (title[:40], t.bpm and "%.1f" % t.bpm, key_name(t.key)))
        ctx.prog(90)
        return t

    def add_url(self, url):
        url = url.strip()
        if not url: return
        self.run_bg("Fetching track", lambda ctx: self._fetch_track(url, ctx), self.add_track)

    def add_url_dialog(self):
        u = simpledialog.askstring(APP, "Paste a URL (YouTube, SoundCloud, ...)\nfiles = off: local paths are disabled.", parent=self.root)
        if u: self.add_url(u)

    def paste_url_track(self):
        try: self.add_url(self.root.clipboard_get())
        except tk.TclError: self.status("Clipboard empty")

    # ---- dialogs ---------------------------------------------------------
    def _themed(self, win):
        th = self.t(); win.configure(bg=th['bg']); self._theme_tree(win, th)

    def _track_labels(self):
        return ["%d. %s" % (i + 1, t.name) for i, t in enumerate(self.project.tracks)]

    def rip_dialog(self):
        win = tk.Toplevel(self.root); win.title("HQ Rip Builder"); win.transient(self.root)
        labels = self._track_labels()
        v1 = tk.StringVar(value=labels[0] if labels else ""); v2 = tk.StringVar(value=labels[1] if len(labels) > 1 else "")
        mode = tk.StringVar(value=MIX_MODES[0][0]); keyv = tk.BooleanVar(value=True); bpmv = tk.StringVar(value="")
        tk.Label(win, text="HQ Rip Builder", font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, columnspan=2, pady=8)
        rows = [("Track 1 (game OST / advertised):", v1), ("Track 2 (joke / meme source):", v2)]
        for i, (lab, v) in enumerate(rows):
            tk.Label(win, text=lab, anchor='w').grid(row=i + 1, column=0, sticky='w', padx=10, pady=3)
            ttk.Combobox(win, textvariable=v, values=labels, width=44).grid(row=i + 1, column=1, padx=10)
        tk.Label(win, text="(pick a track, or paste a URL to fetch one)", anchor='w', font=('Segoe UI', 8)).grid(row=3, column=1, sticky='w', padx=10)
        tk.Label(win, text="Mix mode:").grid(row=4, column=0, sticky='w', padx=10, pady=3)
        ttk.Combobox(win, textvariable=mode, values=[m[0] for m in MIX_MODES], state='readonly', width=30).grid(row=4, column=1, sticky='w', padx=10)
        tk.Label(win, text="Target BPM (blank = T1):").grid(row=5, column=0, sticky='w', padx=10, pady=3)
        tk.Entry(win, textvariable=bpmv, width=8).grid(row=5, column=1, sticky='w', padx=10)
        tk.Checkbutton(win, text="Auto key-align T2 to T1", variable=keyv).grid(row=6, column=1, sticky='w', padx=10)

        def go():
            m = {n: v for n, v in MIX_MODES}[mode.get()]
            a_s, b_s = v1.get().strip(), v2.get().strip()
            try: tb = float(bpmv.get()) if bpmv.get().strip() else None
            except ValueError: tb = None
            win.destroy()
            self.run_bg("Building HQ rip", lambda ctx: self._rip_job(ctx, a_s, b_s, m, tb, keyv.get()), self._rip_done)
        Btn(win, text="  RIP  ", command=go, font=('Segoe UI', 11, 'bold'), padx=16, pady=3).grid(row=7, column=0, columnspan=2, pady=12)
        self._themed(win)

    def _resolve(self, s, ctx):
        m = re.match(r'^(\d+)\.\s', s)
        if m and 0 < int(m.group(1)) <= len(self.project.tracks):
            return self.project.tracks[int(m.group(1)) - 1], False
        if re.match(r'^https?://', s, re.I):
            return self._fetch_track(s, ctx), True
        raise RuntimeError("Pick a track from the list or paste a URL (files = off).")

    def _rip_job(self, ctx, a_s, b_s, mode, tb, align):
        ctx.log("=" * 46); ctx.log("  %s -- HIGH QUALITY RIP (%s)" % (APP, mode)); ctx.log("=" * 46)
        ctx.prog(5)
        a, a_new = self._resolve(a_s, ctx); ctx.prog(15)
        b, b_new = self._resolve(b_s, ctx); ctx.prog(25)
        y, bpm = build_rip(a, b, mode, tb, align, ctx.log, ctx.prog)
        y = fade(normalize(y, -1), 0.05, 2.0)
        ctx.prog(95)
        t = Track("HQ Rip [%s]" % mode, y)
        t.bpm = bpm
        t.key = detect_key(y)
        ctx.log("  RIP COMPLETE  \"%s\"" % random.choice(QUOTES))
        return [x for x, new in ((a, a_new), (b, b_new)) if new], t

    def _rip_done(self, res):
        new, rip = res
        self.push_undo()
        for t in new: self.project.tracks.append(t)
        rip.start = 0.0
        self.project.bpm = float(round(rip.bpm)); self.bpm_v.set("%g" % self.project.bpm)
        self.add_track(rip, undoable=False)
        self.zoom_fit()
        self.status("HQ rip added as a track -- press Space to play, Export to save")

    def export_dialog(self):
        if self.project.length_samples() == 0:
            self.status("Nothing to export."); return
        win = tk.Toplevel(self.root); win.title("Export Mixdown"); win.transient(self.root)
        d = tk.StringVar(value=self.dest); n = tk.StringVar(value="HIGH_QUALITY_RIP")
        f = tk.StringVar(value=".mp3" if FFMPEG else ".wav"); nm = tk.BooleanVar(value=True)
        tk.Label(win, text="Export Mixdown", font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, columnspan=2, pady=8)
        for i, (lab, var) in enumerate((("Destination folder:", d), ("File name:", n))):
            tk.Label(win, text=lab).grid(row=i + 1, column=0, sticky='w', padx=10, pady=3)
            tk.Entry(win, textvariable=var, width=46).grid(row=i + 1, column=1, padx=10)
        tk.Label(win, text="Format:").grid(row=3, column=0, sticky='w', padx=10, pady=3)
        ttk.Combobox(win, textvariable=f, values=[".wav", ".mp3", ".mp4"], state='readonly', width=8).grid(row=3, column=1, sticky='w', padx=10)
        tk.Checkbutton(win, text="Normalize to -1 dB", variable=nm).grid(row=4, column=1, sticky='w', padx=10)
        tk.Checkbutton(win, text="2 s fade-out", variable=self.fade_v).grid(row=5, column=1, sticky='w', padx=10)
        tk.Label(win, text="files = off: type the destination (no file browser).", font=('Segoe UI', 8)).grid(row=6, column=0, columnspan=2)

        def go():
            self.dest = d.get().strip() or self.dest
            name = re.sub(r'[\\/:*?"<>|]', '_', n.get().strip() or "HIGH_QUALITY_RIP")
            path = os.path.join(os.path.expanduser(self.dest), "%s_%s%s" % (name, datetime.now().strftime("%Y%m%d_%H%M%S"), f.get()))
            norm, fo = nm.get(), self.fade_v.get()
            win.destroy()

            def job(ctx):
                ctx.log("[export] mixing down ..."); ctx.prog(20)
                y = self.project.render()
                if norm: y = normalize(y, -1)
                if fo: y = fade(y, 0.02, 2.0)
                ctx.prog(50); ctx.log("[export] encoding %s ..." % f.get())
                export_audio(y, path, ctx.log)
                ctx.log("[export] %s" % path)
                return path
            self.run_bg("Exporting", job, lambda p: messagebox.showinfo(APP, "Exported!\n\n%s\n\n\"%s\"" % (p, random.choice(QUOTES))))
        Btn(win, text="  EXPORT  ", command=go, font=('Segoe UI', 11, 'bold'), padx=16, pady=3).grid(row=7, column=0, columnspan=2, pady=12)
        self._themed(win)

    def show_log(self):
        self.nb.select(1)

    def show_patch_notes(self):
        win = tk.Toplevel(self.root); win.title("Patch Notes"); win.geometry("560x520")
        txt = scrolledtext.ScrolledText(win, font=('Consolas', 9), wrap='word')
        txt.pack(fill='both', expand=True, padx=8, pady=8)
        txt.insert('1.0', PATCH_NOTES); txt.configure(state='disabled')
        Btn(win, text="Close", command=win.destroy, padx=10).pack(pady=(0, 8))
        self._themed(win)

    def show_about(self):
        messagebox.showinfo("About", "%s\n\nfiles = off\naudio: %s\nffmpeg: %s\nyt-dlp: %s\n\n%s" % (
            APP, "sounddevice (live)" if sd else "system player fallback", "yes" if FFMPEG else "no",
            "yes" if yt_dlp else "no", COPYRIGHT_TEXT))

    # ---- theme -----------------------------------------------------------
    def set_theme(self, key=None):
        if key: self.theme.set(key)
        self.apply_theme()

    def cycle_theme(self):
        self.set_theme(THEME_ORDER[(THEME_ORDER.index(self.theme.get()) + 1) % 3])

    def _theme_tree(self, parent, th):
        for w in parent.winfo_children():
            cls = w.winfo_class()
            try:
                if isinstance(w, Btn):
                    w.configure(bg=th['btn'], fg=th['btn_fg'], activebackground=th['btn_active'],
                                activeforeground=th['btn_fg'], disabledforeground=th['muted'])
                elif cls in ('Frame', 'Toplevel'): w.configure(bg=th['bg'])
                elif cls == 'Label': w.configure(bg=w.master.cget('bg'), fg=th['fg'])
                elif cls in ('Entry', 'Spinbox'):
                    w.configure(bg=th['entry_bg'], fg=th['entry_fg'], insertbackground=th['entry_fg'],
                                highlightthickness=0)
                elif cls == 'Scale':
                    w.configure(bg=w.master.cget('bg'), fg=th['fg'], troughcolor=th['entry_bg'],
                                activebackground=th['accent'], highlightthickness=0)
                elif cls == 'Checkbutton':
                    w.configure(bg=w.master.cget('bg'), fg=th['fg'], selectcolor=th['entry_bg'],
                                activebackground=w.master.cget('bg'), activeforeground=th['fg'],
                                highlightthickness=0)
                elif cls == 'Text': w.configure(bg=th['console_bg'], fg=th['console_fg'], insertbackground=th['console_fg'])
                elif cls == 'Menu': w.configure(bg=th['menu_bg'], fg=th['fg'], activebackground=th['accent'], activeforeground='#ffffff')
            except tk.TclError:
                pass
            self._theme_tree(w, th)

    def apply_theme(self):
        th = self.t()
        self.root.configure(bg=th['bg'])
        st = ttk.Style()
        try: st.theme_use('clam')
        except tk.TclError: pass
        st.configure('TProgressbar', troughcolor=th['panel'], background=th['accent'], bordercolor=th['border'],
                     lightcolor=th['accent'], darkcolor=th['accent'])
        st.configure('TNotebook', background=th['bg'], borderwidth=0)
        st.configure('TNotebook.Tab', background=th['panel'], foreground=th['fg'], padding=(10, 3))
        st.map('TNotebook.Tab', background=[('selected', th['accent'])], foreground=[('selected', '#ffffff')])
        st.configure('TScrollbar', background=th['panel'], troughcolor=th['bg'], bordercolor=th['bg'], arrowcolor=th['fg'])
        st.configure('TCombobox', fieldbackground=th['entry_bg'], background=th['panel'], foreground=th['entry_fg'])
        self._theme_tree(self.root, th)
        for w, kw in [(self.banner, {'bg': th['accent']}), (self.banner_title, {'bg': th['accent'], 'fg': '#ffffff'}),
                      (self.banner_sub, {'bg': th['accent'], 'fg': '#d0e8ff'}), (self.transport, {'bg': th['toolbar']}),
                      (self.statusbar, {'bg': th['status'], 'fg': th['fg']}),
                      (self.time_lbl, {'bg': th['entry_bg'], 'fg': th['preview_fg'] if 'preview_fg' in th else '#7ec8ff'}),
                      (self.meter, {'bg': th['entry_bg'], 'highlightbackground': th['border']})]:
            try: w.configure(**kw)
            except tk.TclError: pass
        for w in self.transport.winfo_children():          # transport widgets sit on toolbar colour
            if w.winfo_class() in ('Label', 'Checkbutton', 'Scale') and not isinstance(w, Btn) and w is not self.time_lbl:
                try: w.configure(bg=th['toolbar'])
                except tk.TclError: pass
        self.redraw()

    def quit(self):
        self.player.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Headless self-test
# ---------------------------------------------------------------------------

def selftest():
    ok = True
    def chk(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, extra)
    t0 = time.time()
    d, b, p = synth_drums(120, 8), synth_bass(120, 8), synth_pad(120, 8)
    chk("synth lengths", len(d) == len(b) == len(p), str(len(d)))
    bpm = detect_bpm(d)
    chk("bpm detect ~120", bpm and abs(bpm - 120) < 3, str(bpm))
    k = detect_key(p)
    chk("key detect (Am7 -> root C/A)", k and key_root_major(k) == 0, key_name(k))
    s = time_stretch(b, 1.25)
    chk("stretch length", abs(len(s) - len(b) / 1.25) < 5, "%d vs %d" % (len(s), len(b) / 1.25))
    f_peak = lambda y: np.argmax(np.abs(np.fft.rfft(y[:SR * 2, 0]))) / 2.0
    chk("stretch keeps pitch", abs(f_peak(s) - f_peak(b)) < 3, "%.1f vs %.1f Hz" % (f_peak(s), f_peak(b)))
    sine = to_stereo(0.5 * np.sin(2 * np.pi * 440 * np.arange(SR * 3) / SR))
    ps = pitch_shift(sine, 12)
    chk("pitch +12 doubles f0", len(ps) == len(sine) and abs(f_peak(ps) - 880) < 6, "%.1f Hz (want 880)" % f_peak(ps))
    flat = eq3(d, SR, 1, 1, 1)
    chk("eq flat is identity", np.array_equal(flat, d))
    e = eq3(p, SR, 0.0, 1, 1)
    chk("eq low cut works", np.abs(e).max() <= np.abs(p).max() * 1.05 and np.abs(e).std() < np.abs(p).std())
    A, B = Track("ost", d + b), Track("joke", p)
    A.bpm, A.key, B.bpm, B.key = 120.0, (9, True), 120.0, (2, False)
    for m, fn in MIX_MODES:
        y, tb = build_rip(A, B, fn, None, True, lambda *_: None, lambda *_: None)
        chk("mix %-20s" % m, y.shape[1] == 2 and np.isfinite(y).all() and len(y) > SR, "n=%d" % len(y))
    pr = Project(); pr.tracks += [A, B]; B.mute = True
    blk = pr.mix_block(0, 4096)
    chk("mix_block mute", np.abs(blk).max() > 0 and blk.shape == (4096, 2))
    out = os.path.join(tempfile.mkdtemp(), "t.wav")
    export_audio(fade(normalize(pr.render(), -1)), out)
    chk("export wav", os.path.getsize(out) > 1000)
    if FFMPEG:
        export_audio(pr.render()[:SR * 3], out.replace(".wav", ".mp3")); chk("export mp3", os.path.getsize(out.replace(".wav", ".mp3")) > 1000)
        export_audio(pr.render()[:SR * 3], out.replace(".wav", ".mp4")); chk("export mp4", os.path.getsize(out.replace(".wav", ".mp4")) > 1000)
    try:
        fetch_url("/etc/passwd", tempfile.gettempdir(), print); chk("files=off blocks paths", False)
    except RuntimeError as ex:
        chk("files=off blocks paths", "files = off" in str(ex))
    print("selftest %s in %.1fs" % ("OK" if ok else "FAILED", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if tk is None:
        raise SystemExit("tkinter is not available. Install it (Linux: sudo apt install python3-tk).")
    App().run()
