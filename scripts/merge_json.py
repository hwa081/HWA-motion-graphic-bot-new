#!/usr/bin/env python3
"""Resolve a git rebase conflict in a JSON file of the bot (two runs finished at the same time).
usage: merge_json.py <path>   (run in the middle of a rebase: stage 2 = the other run (already on the branch), stage 3 = this run)
Lists of objects with an "id" (outputs/index.json) -> everything from both runs, this run wins for the same id, newest first.
Other lists -> union.  Objects -> merged (this run wins).  Anything else, or not JSON -> this run's version."""
import json, subprocess, sys


def show(stage, path):
    r = subprocess.run(['git', 'show', ':%d:%s' % (stage, path)], capture_output=True)
    return r.stdout.decode('utf-8', 'replace') if r.returncode == 0 else None


def merge(a, b):
    """a = other run, b = this run"""
    if isinstance(a, list) and isinstance(b, list):
        if all(isinstance(x, dict) and 'id' in x for x in a + b):
            mine = {x['id']: x for x in b}; ids_a = {x['id'] for x in a}
            return [x for x in b if x['id'] not in ids_a] + [mine.get(x['id'], x) for x in a]
        out = list(a)
        for x in b:
            if x not in out: out.append(x)
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items(): out[k] = merge(a[k], v) if k in a and isinstance(v, (dict, list)) and isinstance(a[k], type(v)) else v
        return out
    return b


def main(path):
    theirs = show(3, path)                       # this run
    ours = show(2, path)                         # the other run
    if theirs is None: return 1                  # this run deleted it: caller decides
    try:
        res = merge(json.loads(ours), json.loads(theirs)) if ours is not None else json.loads(theirs)
        text = json.dumps(res, ensure_ascii=False, indent=1)
    except Exception:
        text = theirs
    open(path, 'w', encoding='utf-8').write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
