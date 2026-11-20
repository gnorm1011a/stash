"""Research missing performers via DVD/movie title search.

For each zero-performer scene: extract movie title, search StashDB searchScenes
(TPDB via Stash proxy as fallback), pick candidates from the SAME movie
(title-prefix match), match our file by scene-number + duration, then attach
the candidate's performers (creating local stubs) + 'review' tag.
"""
import json, os, re, sys, time, urllib.request, glob
from collections import defaultdict

GQL = 'http://192.168.0.31:9999/graphql'
EXP = r'M:\Files\Repositories\Personal\Stash\exports'
DRY = '--dry' in sys.argv
SDB = 'https://stashdb.org/graphql'
TPDB = 'https://theporndb.net/graphql'
REVIEW_TAG = '1001'

cfg = open(r'C:\Users\adam\.stash\config.yml', encoding='utf-8').read()
SDB_KEY = re.search(r'apikey:\s*(\S+)\s*\n\s*endpoint:\s*https://stashdb\.org', cfg).group(1)

def post(url, q, key=None):
    h = {'Content-Type': 'application/json'}
    if key: h['ApiKey'] = key
    r = urllib.request.Request(url, data=json.dumps({'query': q}).encode(), headers=h)
    try:
        return json.load(urllib.request.urlopen(r, timeout=90))
    except urllib.error.HTTPError as e:
        return {'errors': [e.read()[:200].decode(errors='replace')]}

def gql(q):
    resp = post(GQL, q)
    if 'errors' in resp: raise RuntimeError(resp['errors'])
    return resp

def lit(v):
    if isinstance(v, list): return '[' + ','.join(lit(x) for x in v) + ']'
    if isinstance(v, dict): return '{' + ','.join(f'{k}:{lit(x)}' for k, x in v.items()) + '}'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return str(v)
    return json.dumps(v, ensure_ascii=False)

# local performer index
perf = json.load(open(os.path.join(EXP, 'performers.json'), encoding='utf-8-sig'))
PNAMES = {}
for p in perf['data']['allPerformers']:
    canon = ' '.join(p['name'].split())
    for n in [canon] + [' '.join(a.split()) for a in (p.get('alias_list') or [])]:
        PNAMES.setdefault(n.lower(), p['id'])

def local_perf(name):
    return PNAMES.get(' '.join(name.split()).lower())

def create_performer(name):
    r = gql('mutation{performerCreate(input:{name:%s}){id}}' % json.dumps(' '.join(name.split())))
    pid = r['data']['performerCreate']['id']
    PNAMES[' '.join(name.split()).lower()] = pid
    return pid

def sdb_search(q):
    r = post(SDB, '{searchScenes(term:%s){scenes{id title date duration '
                  'studio{name} performers{performer{name}}}}}' % json.dumps(q), SDB_KEY)
    return (r.get('data') or {}).get('searchScenes', {}).get('scenes', [])

def tpdb_search(q):
    r = gql('{scrapeSingleScene(source:{stash_box_endpoint:"%s"},input:{query:%s})'
            '{title duration remote_site_id performers{name}}}' % (TPDB, json.dumps(q)))
    v = (r.get('data') or {}).get('scrapeSingleScene') or []
    return v if isinstance(v, list) else [v]

STOP = set('''a an and the of in on at for to with from by'''.split())
def toks(s):
    return {t for t in re.findall(r'[a-z0-9]+', (s or '').lower()) if t not in STOP}

def scene_num(s):
    m = re.search(r'(?i)scene\s*(\d+)', s or '')
    return int(m.group(1)) if m else None

def edition_digits(s):
    # numeric tokens NOT preceded by scene/ep/part/vol/chapter/#
    t = re.findall(r'[a-z0-9#]+', (s or '').lower())
    out = set()
    for i, tok in enumerate(t):
        if not tok.isdigit():
            continue
        prev = t[i-1] if i else ''
        if prev in ('scene', 'ep', 'episode', 'part', 'vol', 'chapter', '#'):
            continue
        out.add(tok)
    return out

# scope
scope = json.load(open(os.path.join(EXP, 'dvd-research-scope.json')))
d = json.load(open(sorted(glob.glob(os.path.join(EXP, 'unmatched-scene-search-*.json')))[-1], encoding='utf-8'))
targets = [s for s in scope['zero_performer'] if d.get(s)]

# cluster by query (movie title) to dedupe box searches
by_title = defaultdict(list)
for s in targets:
    by_title[d[s]['query'].lower()].append(s)
print(len(targets), 'scenes |', len(by_title), 'distinct titles')

cand_cache = {}
def movie_scenes(title):
    if title in cand_cache: return cand_cache[title]
    out = []
    for s in sdb_search(title):
        out.append({'box': 'stashdb', 'sid': s.get('id'), 'title': s.get('title') or '',
                    'duration': s.get('duration'),
                    'performers': [p['performer']['name'] for p in (s.get('performers') or [])]})
    if not out:
        for s in tpdb_search(title):
            out.append({'box': 'tpdb', 'sid': s.get('remote_site_id'), 'title': s.get('title') or '',
                        'duration': s.get('duration'),
                        'performers': [p['name'] for p in (s.get('performers') or [])]})
    cand_cache[title] = out
    return out

results = {}
t0 = time.time()
for i, (tkey, sids) in enumerate(by_title.items()):
    rec0 = d[sids[0]]
    mtoks = toks(rec0['query'])
    scenes = movie_scenes(tkey)
    # keep candidates from THIS movie: every movie-title token must appear
    pool = []
    for c in scenes:
        ct = toks(c['title'])
        if mtoks and mtoks <= ct and edition_digits(rec0['query']) <= edition_digits(c['title']):
            pool.append(c)
    for sid in sids:
        rec = d[sid]
        fnum = scene_num(rec['basename'])
        fdur = rec.get('fdur')
        best = None; best_sc = -1
        for c in pool:
            cnum = scene_num(c['title'])
            dur_ok = bool(c['duration'] and fdur and abs(c['duration'] - fdur) <= 10)
            num_ok = bool(fnum and cnum and fnum == cnum)
            num_bad = bool(fnum and cnum and fnum != cnum)
            if num_bad and not dur_ok:
                continue  # different scene of the same movie and duration doesn't back it
            sc = (2 if num_ok else 0) + (1 if dur_ok else 0) - (1 if num_bad else 0)
            if sc > best_sc:
                best, best_sc = c, sc
        results[sid] = {'basename': rec['basename'], 'query': rec['query'], 'fdur': fdur,
                        'fnum': fnum, 'pool': len(pool),
                        'best': best, 'conf': 'exact' if best_sc >= 3 else None}
    if i % 30 == 0:
        print(i, '/', len(by_title), f'{time.time()-t0:.0f}s', file=sys.stderr)

json.dump(results, open(os.path.join(EXP, 'dvd-research-results.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
n_conf = sum(1 for v in results.values() if v['conf'])
print('confident:', n_conf, '| candidates-in-pool:', sum(v['pool'] for v in results.values()))

# apply: attach performers for confident matches + review tag
applied = failed = 0
log = []
for sid, res in results.items():
    if not res['best'] or res['conf'] != 'exact':
        continue
    names = res['best'].get('performers') or []
    if not names:
        continue
    try:
        pids = []
        for n in names:
            pid = local_perf(n) or (None if DRY else create_performer(n))
            if pid: pids.append(pid)
        r = gql('{findScene(id:"%s"){performers{id} tags{id} stash_ids{endpoint}}}' % sid)
        sc = r['data']['findScene']
        pids = sorted({p['id'] for p in sc['performers']} | set(pids), key=int)
        tids = sorted({t['id'] for t in sc['tags']} | {REVIEW_TAG}, key=int)
        ep = 'https://stashdb.org/graphql' if res['best']['box'] == 'stashdb' else TPDB
        sids2 = sc['stash_ids'] + ([{'endpoint': ep, 'stash_id': res['best']['sid']}]
                if res['best']['sid'] and not any(x['endpoint'] == ep for x in sc['stash_ids']) else [])
        fields = {'id': str(sid), 'performer_ids': pids, 'tag_ids': tids, 'stash_ids': sids2}
        if not DRY:
            gql('mutation{sceneUpdate(input:%s){id}}' % ('{' + ','.join(f'{k}:{lit(v)}' for k, v in fields.items()) + '}'))
        applied += 1
        log.append({'id': sid, 'conf': res['conf'], 'basename': res['basename'],
                    'match': res['best']['title'], 'performers': names, 'fields': fields})
    except Exception as e:
        failed += 1
        log.append({'id': sid, 'result': 'error', 'error': str(e)[:200]})

# tag-only pass: movie indexed but scene unverified -> 'review' tag as a lead
tagged = tfail = 0
for sid, res in results.items():
    if res['conf'] == 'exact' or res['pool'] == 0:
        continue
    try:
        r = gql('{findScene(id:"%s"){tags{id}}}' % sid)
        tids = sorted({t['id'] for t in r['data']['findScene']['tags']} | {REVIEW_TAG}, key=int)
        if not DRY:
            gql('mutation{sceneUpdate(input:{id:"%s",tag_ids:%s}){id}}' % (sid, lit(tids)))
        tagged += 1
        log.append({'id': sid, 'result': 'review-tag-only', 'basename': res['basename'],
                    'lead': res['best']['title'] if res['best'] else None,
                    'pool': res['pool']})
    except Exception as e:
        tfail += 1
        log.append({'id': sid, 'result': 'tag-error', 'error': str(e)[:200]})

json.dump(log, open(os.path.join(EXP, 'dvd-research-apply-log.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('applied:', applied, '| failed:', failed, '| tagged-review-only:', tagged, '| dry:', DRY)
