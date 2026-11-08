"""mgl.llm - more than one AI.

Gemini stays the default (it has its own client in mgl.gemini). On top of it, ANY service with an OpenAI-compatible API can be added from the Studio page
(OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Together, your own URL). Settings come from the environment (set by the GitHub workflow):

    GEMINI_API_KEY            secret
    AI_PROVIDERS              variable, JSON list [{"id","name","base_url","model"}]   (no keys inside)
    AI_KEY_<ID>               secret per provider (id upper-cased, non letters/digits -> _)
    AI_KEY_AI1 .. AI_KEY_AI8  the 8 slots the workflow passes explicitly (no toJSON(secrets): GitHub flags that as malicious).
    AI_ALL_SECRETS            optional, old style: all secrets as JSON; only AI_KEY_* entries are used
    AI_PROVIDER / AI          which one first (run input "ai" wins over the variable)
    AI_FALLBACK               "false" = never switch to another AI when the chosen one fails

ask = make_multi_ask(providers, ...) has the same shape as agent.make_ask(): ask(system, contents, json_mode) -> text.
The contents are Gemini-shaped ({'role', 'parts': [{'text'} | {'inlineData'}]}); they are converted for OpenAI-style services (text + images).
"""
import json, os, re, time, urllib.request, urllib.error
from . import gemini
from . import timing as _timing

GeminiError = gemini.GeminiError


class Provider:
    def __init__(self, pid, name, kind, key, base_url='', model=''):
        self.id, self.name, self.kind, self.key, self.base_url, self.model = pid, name, kind, key, base_url.rstrip('/'), model

    def __repr__(self): return 'Provider(%s,%s,%s)' % (self.id, self.kind, self.model)


def secret_name(pid): return 'AI_KEY_' + re.sub(r'[^A-Z0-9]', '_', pid.upper())


def absorb_secrets(env=None):
    """move AI_KEY_* out of the AI_ALL_SECRETS JSON into plain env vars and delete the JSON (so no other secret stays in the environment)"""
    env = os.environ if env is None else env
    raw = env.pop('AI_ALL_SECRETS', '') if hasattr(env, 'pop') else ''
    if not raw: return 0
    n = 0
    try:
        for k, v in (json.loads(raw) or {}).items():
            if k.startswith('AI_KEY_') and isinstance(v, str) and v.strip() and not env.get(k):
                env[k] = v; n += 1
    except Exception:
        pass
    return n


def providers_from_env(env=None):
    env = os.environ if env is None else env
    out = []
    gks = [k for k in re.split(r'[,;\s]+', (env.get('GEMINI_API_KEY') or '').strip().strip('"\'')) if k]      # one key, or several separated by commas / new lines
    for i, gk in enumerate(dict.fromkeys(gks)):
        out.append(Provider('gemini' if i == 0 else 'gemini%d' % (i + 1), 'Gemini' if i == 0 else 'Gemini %d' % (i + 1), 'gemini', gk, '', (env.get('GEMINI_MODEL') or '').strip()))
    try:
        items = json.loads(env.get('AI_PROVIDERS') or '[]')
    except Exception:
        items = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not it.get('id') or not it.get('base_url') or not it.get('model'): continue
        key = (env.get(secret_name(str(it['id']))) or '').strip()
        if key: out.append(Provider(str(it['id']), str(it.get('name') or it['id']), 'openai', key, str(it['base_url']), str(it['model'])))
    if (env.get('LOCAL_AI') or '').strip().lower() in ('1', 'true', 'on', 'yes'):          # free, unlimited, slow: the workflow started Ollama on the runner; it only follows when every other AI failed
        out.append(Provider('local', 'Local Qwen (free)', 'ollama', 'local', (env.get('LOCAL_AI_URL') or 'http://127.0.0.1:11434').strip(), (env.get('LOCAL_AI_MODEL') or 'qwen3.5:4b').strip()))
    return out


def order(providers, wanted='', fallback=True):
    """chosen provider first; the others after it unless fallback is off"""
    wanted = (wanted or '').strip().lower()
    first = [p for p in providers if p.id.lower() == wanted] or providers[:1]
    rest = [p for p in providers if p not in first]
    return first + (rest if fallback else [])


# ------------------------------------------------------------------ OpenAI-compatible client
def to_messages(system, contents):
    msgs = []
    if system: msgs.append({'role': 'system', 'content': system})
    for c in contents:
        role = 'assistant' if c.get('role') == 'model' else 'user'
        parts = []
        for p in c.get('parts', []):
            if 'text' in p: parts.append({'type': 'text', 'text': p['text']})
            elif 'inlineData' in p:
                d = p['inlineData']; parts.append({'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (d.get('mimeType', 'image/png'), d.get('data', ''))}})
        if role == 'assistant': msgs.append({'role': 'assistant', 'content': ''.join(x['text'] for x in parts if x['type'] == 'text')})
        elif all(x['type'] == 'text' for x in parts): msgs.append({'role': 'user', 'content': '\n'.join(x['text'] for x in parts)})
        else: msgs.append({'role': 'user', 'content': parts})
    return msgs


def _http(url, key, body, timeout=240):
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST', headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key, 'User-Agent': 'motion-graphic-bot'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8')), r.headers
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try: return e.code, json.loads(raw), e.headers
        except Exception: return e.code, {'error': {'message': raw[:400]}}, e.headers
    except Exception as ex:
        raise GeminiError('network error: %s' % ex)


def _msg(j):
    e = j.get('error') if isinstance(j, dict) else None
    if isinstance(e, dict): return str(e.get('message') or e)[:300]
    return str(e or j)[:300]


def openai_generate(p, system, contents, json_mode=True, temperature=0.8, max_tokens=8000):
    body = {'model': p.model, 'messages': to_messages(system, contents), 'temperature': temperature, 'max_tokens': max_tokens}
    if json_mode: body['response_format'] = {'type': 'json_object'}
    url = p.base_url + '/chat/completions'
    st, j, hd = _http(url, p.key, body)
    for _ in range(3):                      # services differ: drop options they reject
        if st != 400: break
        m = _msg(j).lower()
        if 'response_format' in body and ('response_format' in m or 'json' in m): body.pop('response_format')
        elif 'max_tokens' in body and ('max_tokens' in m or 'max_completion_tokens' in m):
            body['max_completion_tokens'] = body.pop('max_tokens')
        elif 'temperature' in body and 'temperature' in m: body.pop('temperature')
        else: break
        st, j, hd = _http(url, p.key, body)
    if st == 200:
        try: txt = j['choices'][0]['message']['content']
        except Exception: raise GeminiError('%s: unexpected answer %s' % (p.name, str(j)[:200]))
        if isinstance(txt, list): txt = ''.join(x.get('text', '') for x in txt if isinstance(x, dict))
        txt = re.sub(r'(?is)<think>.*?</think>', '', txt or '').strip()
        if not txt: raise GeminiError('%s: empty answer' % p.name)
        return txt
    ex = GeminiError('HTTP %s from %s (%s): %s' % (st, p.name, p.model, _msg(j)))
    ex.status = st
    try: ex.retry_after = float(hd.get('retry-after')) if hd and hd.get('retry-after') else None
    except Exception: ex.retry_after = None
    raise ex


def openai_ask(p, system, contents, json_mode=True, temperature=0.8, log=print, max_wait=90):
    last = None
    for attempt in range(3):
        try:
            log('  -> %s / %s (try %d)' % (p.name, p.model, attempt + 1))
            return openai_generate(p, system, contents, json_mode, temperature)
        except GeminiError as ex:
            last = ex; st = getattr(ex, 'status', None)
            low = str(ex).lower()
            if st in (401, 402, 403) or (st == 429 and any(w in low for w in ('no credits', 'insufficient_quota', 'exceeded your current quota', 'billing', 'add credits'))):
                if st in (401, 403):
                    ex = GeminiError('%s: API key rejected (%s)' % (p.name, _msg({'error': str(ex)}))); ex.status = st
                ex.dead = True; raise ex                       # no money / no access: waiting does not help
            if st == 413: raise ex                             # too large for this service: the caller shortens the prompt
            if st in (429, 500, 502, 503, 504) and attempt < 2:
                wait = min(max_wait, getattr(ex, 'retry_after', None) or 8 * (attempt + 1)); log('     %s - waiting %.0fs then retrying' % (st, wait)); time.sleep(wait); continue
            break
    raise last


# ------------------------------------------------------------------ a small model on the runner itself (Ollama, CPU): free and unlimited, but slow
LOCAL_INPUT_TOKENS = 11000                  # prompts for it are always shortened to about this size (a 4B model on 4 CPU cores)


def ollama_generate(p, system, contents, json_mode=True, temperature=0.7):
    msgs = []
    for m in to_messages(system, contents):
        c = m['content']
        if isinstance(c, list): c = '\n'.join(x.get('text', '') for x in c if x.get('type') == 'text')      # this model is used for text only
        msgs.append({'role': m['role'], 'content': c})
    body = {'model': p.model, 'messages': msgs, 'stream': False, 'think': False, 'options': {'num_ctx': 16384, 'temperature': temperature, 'num_predict': 9000}}
    if json_mode: body['format'] = 'json'
    url = p.base_url + '/api/chat'
    st, j, hd = _http(url, 'local', body, timeout=int(os.environ.get('LOCAL_AI_TIMEOUT', '1500') or 1500))
    if st == 400 and 'think' in body and 'think' in _msg(j).lower():
        body.pop('think'); st, j, hd = _http(url, 'local', body, timeout=int(os.environ.get('LOCAL_AI_TIMEOUT', '1500') or 1500))
    if st == 200:
        txt = ((j.get('message') or {}).get('content') or '') if isinstance(j, dict) else ''
        txt = re.sub(r'(?is)<think>.*?</think>', '', txt).strip()
        if not txt: raise GeminiError('%s: empty answer' % p.name)
        return txt
    ex = GeminiError('HTTP %s from %s (%s): %s' % (st, p.name, p.model, _msg(j)))
    ex.status = st; ex.retry_after = None
    raise ex


def _has_images(contents):
    return any('inlineData' in x for c in contents for x in c.get('parts', []))


# ------------------------------------------------------------------ shorter prompts for services with a small tokens-per-minute limit
def _chars(system, contents):
    return len(system or '') + sum(len(p.get('text', '')) for c in contents for p in c.get('parts', []))


def _map_text(contents, fn):
    return [{**c, 'parts': [({**p, 'text': fn(p['text'])} if 'text' in p else p) for p in c.get('parts', [])]} for c in contents]


_MEM = re.compile(r'(=== MEMORY[^\n]*===\n)(.*?)(\nReturn ONLY the JSON object\.)', re.S)


def shrink(system, contents, limit_tokens, requested_tokens=None, safety=0.8):
    """cut the optional parts of a prompt until it should fit limit_tokens (the service said "Limit N, Requested M").
    Order: the working examples in the system prompt, then the memory block (to 1500 characters, then gone). Returns (system, contents, fits)."""
    total = _chars(system, contents)
    cpt = (total / float(requested_tokens)) if requested_tokens else 3.3          # characters per token, measured from the service's own count
    goal = int(limit_tokens * safety * cpt)
    if total <= goal: return system, contents, True
    system = re.sub(r'EXAMPLE "[^"]*":\n[^\n]*\n*', '', system or '')
    for keep in (1500, 0):
        if _chars(system, contents) <= goal: break
        contents = _map_text(contents, lambda t, k=keep: _MEM.sub(lambda m: (m.group(1) + m.group(2)[:k] + m.group(3)) if k else m.group(3), t))
    return system, contents, _chars(system, contents) <= goal


def _too_large(ex):
    m = re.search(r'Limit (\d+), Requested (\d+)', str(ex))
    return (int(m.group(1)), int(m.group(2))) if m else (6000, None)


# ------------------------------------------------------------------ the multi-provider ask()
def make_multi_ask(providers, budget, log=print, budget_error=None):
    """providers: ordered list. Same interface as agent.make_ask(). The provider that answered moves to the front for the next request."""
    chain = list(providers)
    gem_models = {}
    used = []
    cool = {}                                  # provider id -> epoch until which it is skipped (its quota is used up)
    dead = {}                                  # provider id -> why it is skipped for the whole run (no access, no credits)
    small = {}                                 # provider id -> its tokens-per-minute limit, learned from a 413 (later prompts are shortened at once)
    BudgetError = budget_error or GeminiError
    spread = os.environ.get('AI_SPREAD', 'true').strip().lower() not in ('false', '0', 'no', 'off')
    rr = [abs(hash(os.environ.get('JOB', '') or str(os.getpid()))) % 997]      # every run / lane starts on another key

    def candidates():
        """same kind as the first AI are used in turn (their quotas add up, one dead key is skipped); other kinds only follow as a fallback"""
        now = time.time()
        alive = [p for p in chain if p.id not in dead]
        if not alive: raise GeminiError('every AI is unusable in this run:\n  ' + '\n  '.join('%s: %s' % (k, v) for k, v in list(dead.items())[-6:]))
        live = [p for p in alive if cool.get(p.id, 0) <= now] or list(alive)
        if not spread or len(live) < 2: return live
        k0 = live[0].kind
        same = [p for p in live if p.kind == k0]; other = [p for p in live if p.kind != k0]
        if len(same) > 1:
            r = rr[0] % len(same); same = same[r:] + same[:r]
        rr[0] += 1
        return same + other

    def ask(system, contents, json_mode=True):
        if ask.calls >= ask.budget:
            raise BudgetError('request budget of %d reached for this run (protects the free quota; raise it with the MAX_REQUESTS variable)' % ask.budget)
        ask.calls += 1
        problems = []
        _t_req = time.time()
        for p in candidates():
            try:
                if p.kind == 'ollama':
                    if _has_images(contents): continue                 # it cannot look at pictures (Gemini does that)
                    s1, c1, _ok = shrink(system, contents, LOCAL_INPUT_TOKENS, None, safety=0.9)
                    log('   -> %s / %s (free, runs on this computer - slow, please wait)' % (p.name, p.model))
                    txt = ollama_generate(p, s1, c1, json_mode=json_mode)
                    label = p.id + '/' + p.model
                elif p.kind == 'gemini':
                    if p.id not in gem_models:
                        gem_models[p.id] = [m.strip() for m in p.model.split(',') if m.strip()] or gemini.choose_models(p.key)
                    txt, model = gemini.ask(p.key, gem_models[p.id], system, contents, json_mode=json_mode, log=log)
                    label = 'gemini/' + model
                else:
                    s1, c1 = system, contents
                    if p.id in small:
                        s1, c1, _ok = shrink(s1, c1, small[p.id])
                    try:
                        txt = openai_ask(p, s1, c1, json_mode=json_mode, log=log)
                    except GeminiError as ex413:
                        if getattr(ex413, 'status', None) != 413: raise
                        lim, req = _too_large(ex413)
                        s2, c2, fits = shrink(system, contents, lim, req)
                        small[p.id] = lim
                        if not fits and _chars(s2, c2) >= _chars(s1, c1): raise
                        log('   too large for %s (limit %d tokens) - trying again with a shorter prompt' % (p.name, lim))
                        txt = openai_ask(p, s2, c2, json_mode=json_mode, log=log)
                    label = p.id + '/' + p.model
                if label not in used: used.append(label)
                if chain[0] is not p and p.kind != 'ollama' and (not spread or p.kind != chain[0].kind): chain.remove(p); chain.insert(0, p)      # another kind of AI had to step in: it leads from now on
                _timing.add('ai_request', time.time() - _t_req, label)
                return txt
            except GeminiError as ex:
                problems.append('%s: %s' % (p.name, ex))
                if getattr(ex, 'dead', False): dead[p.id] = str(ex)[:160]; log('   %s cannot be used in this run (no access / no credits) - skipping it from now on' % p.name)
                elif getattr(ex, 'status', None) == 413: cool[p.id] = time.time() + 3600
                if getattr(ex, 'quota', False) or getattr(ex, 'status', None) == 429: cool[p.id] = time.time() + 600
                if len(chain) > 1: log('   %s failed - trying the next AI' % p.name)
        _timing.add('ai_request', time.time() - _t_req, 'failed')
        raise GeminiError('every AI failed:\n  ' + '\n  '.join(problems[-6:]))
    ask.used, ask.calls, ask.budget = used, 0, budget
    ask.providers = chain
    return ask


# ------------------------------------------------------------------ connection test (for mode "checks")
def test_provider(p):
    try:
        if p.kind == 'gemini':
            models = gemini.choose_models(p.key)
            txt, model = gemini.ask(p.key, models, None, [{'role': 'user', 'parts': [gemini.text_part('Reply with the single word OK')]}], json_mode=False, log=lambda *a: None)
            return True, 'answered with %s' % model
        txt = openai_ask(p, None, [{'role': 'user', 'parts': [{'text': 'Reply with the single word OK'}]}], json_mode=False, log=lambda *a: None)
        return True, 'answered: %s' % txt.strip()[:40]
    except GeminiError as ex:
        return False, str(ex)[:240]
