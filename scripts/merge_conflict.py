"""Two bot runs may finish at the same time and both change outputs/index.json or memory/*.json.
Usage: merge_conflict.py <target> <remote_version> <my_version>   -> writes the merged file to <target>; exit 1 = could not merge (caller keeps the remote one)."""
import json, os, sys


def load(p):
    try:
        t = open(p, encoding='utf-8').read()
        return json.loads(t) if t.strip() else None
    except Exception:
        return None


def key(x):
    return ('id', x['id']) if isinstance(x, dict) and 'id' in x else ('j', json.dumps(x, sort_keys=True))


def merge(remote, mine):
    if remote is None: return mine
    if mine is None: return remote
    if isinstance(remote, list) and isinstance(mine, list):
        seen = {key(x): i for i, x in enumerate(remote)}; out = list(remote)
        for x in mine:
            k = key(x)
            if k in seen:
                if k[0] == 'id' and isinstance(x, dict):                 # same entry: keep the remote one, but take fields only I have
                    r = out[seen[k]]
                    if isinstance(r, dict): out[seen[k]] = dict(x, **r)
            else: out.append(x); seen[k] = len(out) - 1
        if out and all(isinstance(x, dict) and 'date' in x for x in out): out.sort(key=lambda e: str(e.get('date', '')), reverse=True)     # outputs/index.json: newest first
        return out
    if isinstance(remote, dict) and isinstance(mine, dict):
        out = dict(remote)
        for k, v in mine.items():
            out[k] = merge(out[k], v) if k in out and isinstance(v, (dict, list)) and isinstance(out[k], type(v)) else out.get(k, v)
        return out
    return remote


if __name__ == '__main__':
    target, rp, mp = sys.argv[1:4]
    r, m = load(rp), load(mp)
    if r is None and m is None: sys.exit(1)
    res = merge(r, m)
    os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
    json.dump(res, open(target, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
