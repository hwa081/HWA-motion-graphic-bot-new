import sys, os, tempfile, wave, struct, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
d = tempfile.mkdtemp(); os.chdir(d)
os.makedirs('SFX/sub')
def wav(p, sec, f):
    w = wave.open(p, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * f * i / 44100))) for i in range(int(44100 * sec)))); w.close()
wav('SFX/whoosh_1.wav', 0.5, 300); wav('SFX/sub/my sound 7.wav', 0.2, 900); wav('SFX/sub/zzz.wav', 1.0, 200)
os.environ.pop('SFX_PACK', None)
from mgl import sound
pk = sound.load_pack()
print(sound.pack_summary(), {k: len(v) for k, v in pk.items()})
assert len(pk.get('whoosh', [])) >= 2 and len(pk.get('pop', [])) >= 1
