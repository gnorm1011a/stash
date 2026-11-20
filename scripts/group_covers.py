"""Fetch real DVD box covers from TPDB movies API for created groups.
Matches by title tokens + edition digits (+studio when known).
Sets group front_image/back_image from TPDB movie 'image'/'back_image'.
"""
import json, os, re, sys, time, urllib.request, base64

EXP = r'M:\Files\Repositories\Personal\Stash\exports'
GQL = 'http://192.168.0.31:9999/graphql'
DRY = '--dry' in sys.argv

cfg = open(r'M:\Apps\stash\config\config.yml', encoding='utf-8').read()
TPDB_KEY = re.search(r'apikey:\s*(\S+)\s*\n\s*endpoint:\s*https://theporndb', cfg).group(1)

def gql(q):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    try:
        resp = json.load(urllib.request.urlopen(r, timeout=120))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read()[:300].decode(errors='replace'))
    if 'errors' in resp: raise RuntimeError(resp['errors'])
    return resp

def tpdb_movies(q):
    r = urllib.request.Request('https://api.theporndb.net/movies?q=' + urllib.parse.quote(q),
        headers={'Authorization': 'Bearer ' + TPDB_KEY, 'Accept': 'application/json',
                 'User-Agent': 'Mozilla/5.0'})
    try:
        d = json.load(urllib.request.urlopen(r, timeout=30))
        return d.get('data', [])
    except Exception:
        return []

STOP = set('a an and the of in on at for to with from by'.split())
def toks(s):
    return {t for t in re.findall(r'[a-z0-9]+', (s or '').lower()) if t not in STOP}
def edition_digits(s):
    t = re.findall(r'[a-z0-9#]+', (s or '').lower())
    out = set()
    for i, tok in enumerate(t):
        if not tok.isdigit(): continue
        prev = t[i-1] if i else ''
        if prev in ('scene','ep','episode','chapter'): continue  # scene numbering, not edition
        out.add(str(int(tok)))
    return out

def fetch_b64(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=60).read()
        ct = 'image/png' if data[:4] == b'\x89PNG' else ('image/webp' if data[:4] == b'RIFF' else 'image/jpeg')
        return 'data:%s;base64,%s' % (ct, base64.b64encode(data).decode())
    except Exception:
        return None

def lit(v):
    if isinstance(v, str): return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return str(v)
    if isinstance(v, list): return '[' + ','.join(lit(x) for x in v) + ']'
    return json.dumps(v)

props = json.load(open(os.path.join(EXP, 'group-proposal.json'), encoding='utf-8'))
todo = [p for p in props if p['files'] >= 2 or p['indexed'] > 0]

# map group name -> stash group id
gid_cache = {}
def find_group(name):
    if name in gid_cache: return gid_cache[name]
    r = gql('{findGroups(group_filter:{name:{value:%s,modifier:EQUALS}}){groups{id name}}}' % json.dumps(name))
    gid = None
    for g in r['data']['findGroups']['groups']:
        if g['name'].lower() == name.lower(): gid = g['id']
    gid_cache[name] = gid
    return gid

ok = miss = errs = 0
log = []
for i, p in enumerate(todo):
    name = ' '.join(p['movie'].split())
    mtoks, mdig = toks(name), edition_digits(name)
    cands = tpdb_movies(name)
    STRUCT = {'scene','ep','episode','part','vol','chapter','vols','pts'}
    def extra_alpha(ct_):
        return {t for t in ct_ - mtoks if not t.isdigit() and t not in STRUCT}
    def studio_ok(m):
        if not p.get('studio'): return False
        site = m.get('site') or {}
        sname = (site.get('name') or '').lower() if isinstance(site, dict) else ''
        return bool(sname) and toks(sname) == toks(p['studio'])
    scored = []
    for m in cands:
        ct, cd = toks(m.get('title')), edition_digits(m.get('title') or '')
        if not (mtoks <= ct): continue
        if mdig != cd and (mdig or cd): continue   # edition digits must agree exactly
        extra = extra_alpha(ct)
        if extra and not studio_ok(m): continue    # extra words need studio corroboration
        scored.append((len(extra), -len(ct), m))
    best = sorted(scored, key=lambda x: (x[0], x[1]))[0][2] if scored else None
    if not best:
        miss += 1
        log.append({'group': name, 'result': 'no-tpdb-movie'})
        continue
    front = best.get('image') or (best.get('posters') or {}).get('large') or (best.get('posters') or {}).get('full')
    back = best.get('back_image') or (best.get('background_back') or {}).get('large')
    entry = {'group': name, 'tpdb_title': best.get('title'), 'tpdb_id': best.get('id'),
             'front': bool(front), 'back': bool(back),
             'cast': [pp.get('name') for pp in (best.get('performers') or [])]}
    gid = find_group(name)
    if not gid:
        entry['result'] = 'no-group'; log.append(entry); continue
    if not DRY:
        try:
            fields = {'id': gid}
            fb = fetch_b64(front) if front else None
            bb = fetch_b64(back) if back else None
            if fb: fields['front_image'] = fb
            if bb: fields['back_image'] = bb
            if len(fields) > 1:
                gql('mutation{groupUpdate(input:%s){id}}' % ('{' + ','.join(f'{k}:{lit(v)}' for k, v in fields.items()) + '}'))
                entry['result'] = 'cover-set'; ok += 1
            else:
                entry['result'] = 'no-images'
        except Exception as e:
            entry['result'] = 'error'; entry['error'] = str(e)[:200]; errs += 1
    else:
        entry['result'] = 'dry'; ok += 1
    log.append(entry)
    if i % 20 == 0: print(i, '/', len(todo), file=sys.stderr)

json.dump(log, open(os.path.join(EXP, 'group-covers-log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('covers set:', ok, '| no tpdb movie:', miss, '| errors:', errs, '| dry:', DRY)
