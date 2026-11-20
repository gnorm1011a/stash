"""Check-2 v2: direct StashDB searchScenes + TPDB via Stash proxy.

Per unmatched scene: build title query from filename, search both boxes,
score candidates on duration (+-8s strong / +-30s loose) + title token overlap.
Output: exports/unmatched-scene-search-<ts>.json
"""
import json, os, re, sys, time, urllib.request

GQL = 'http://192.168.0.31:9999/graphql'
REPO = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash'
EXP = os.path.join(REPO, 'exports')
LIMIT_N = int(sys.argv[sys.argv.index('--limit')+1]) if '--limit' in sys.argv else 0

def post(url, q, key=None):
    h = {'Content-Type': 'application/json'}
    if key: h['ApiKey'] = key
    r = urllib.request.Request(url, data=json.dumps({'query': q}).encode(), headers=h)
    for a in range(4):
        try:
            return json.load(urllib.request.urlopen(r, timeout=60))
        except Exception:
            if a == 3: return {}
            time.sleep(4)

def gql(q):
    return post(GQL, q)

KEYS = {b['endpoint']: b['api_key'] for b in
        gql('{configuration{general{stashBoxes{endpoint api_key}}}}')
        ['data']['configuration']['general']['stashBoxes']}
SDB = 'https://stashdb.org/graphql'
TPDB = 'https://theporndb.net/graphql'

# performer names for exclusion
perf = json.load(open(os.path.join(EXP, 'performers.json'), encoding='utf-8-sig'))
PNAMES = {' '.join(p['name'].split()).lower() for p in perf['data']['allPerformers']}
for p in perf['data']['allPerformers']:
    for a in p.get('alias_list') or []:
        PNAMES.add(' '.join(a.split()).lower())

STOP = {'ui','dvd','xxx','dvdrip','hd','ts','rm','compilation','amateur','teen',
        'asian','euro','russian','thai','latina','ebony','milf','scene','part',
        'of','the','a','an','and','in','on','for','with','to','by','at','2','3'}

def tokens(s):
    return set(re.findall(r'[a-z]+', s.lower())) - STOP

def build_query(base):
    b = os.path.splitext(base)[0]
    b = re.sub(r'\([^)]*\)\s*$', '', b)
    b = re.sub(r'-\([^)]*\)-.*', '', b)
    parts = []
    for x in b.split(' - '):
        x = re.sub(r'[\[\]{}]', ' ', x)
        x = ' '.join(x.split()).strip(' -._')
        sl = x.lower()
        if not x or sl in STOP or sl in PNAMES or len(x) < 3:
            continue
        if re.match(r'(?i)^scene\s*\d+$', sl):
            continue
        parts.append(x)
    parts.sort(key=len, reverse=True)
    return ' '.join(parts[:2])[:80], parts

def sdb_search(q):
    r = post(SDB, '{searchScenes(term:%s){scenes{id title date duration '
                  'studio{name} performers{performer{name}}}}}' % json.dumps(q),
             KEYS.get(SDB))
    return (r.get('data') or {}).get('searchScenes', {}).get('scenes', [])

def tpdb_search(q):
    r = gql('{scrapeSingleScene(source:{stash_box_endpoint:"%s"},input:{query:%s})'
            '{title date duration remote_site_id studio{name} performers{name} tags{name}}}'
            % (TPDB, json.dumps(q)))
    v = (r.get('data') or {}).get('scrapeSingleScene') or []
    return v if isinstance(v, list) else [v]

def scene_num(base):
    m = re.search(r'(?i)scene\s*(\d+)', base)
    return int(m.group(1)) if m else None

def score(c, fdur, ftoks, fnum=None):
    sd = c.get('duration')
    d_match = sd is not None and fdur and abs(sd - fdur) <= 8
    d_loose = sd is not None and fdur and abs(sd - fdur) <= 30
    ov = len(ftoks & tokens(c.get('title') or '')) / max(1, len(ftoks))
    sc = (50 if d_match else 20 if d_loose else 0) + int(ov * 50)
    # scene-number corroboration
    cnum = scene_num(c.get('title') or '') or scene_num(c.get('code') or '')
    if fnum and cnum:
        sc += 15 if fnum == cnum else -25
    return sc, bool(d_match), round(ov, 2)

ids = json.load(open(os.path.join(EXP, 'identify-target-ids.json')))
targets = []
for i in range(0, len(ids), 100):
    parts = ' '.join('s%d:findScene(id:"%d"){id stash_ids{stash_id} files{basename duration}}'
                     % (i2, i2) for i2 in ids[i:i+100])
    r = gql('{' + parts + '}')
    for s in r['data'].values():
        if s and not s['stash_ids'] and s['files']:
            targets.append((int(s['id']), s['files'][0]['basename'], s['files'][0]['duration']))
print(len(targets), 'scenes to search')

out = {}
t = time.time()
todo = targets[:LIMIT_N] if LIMIT_N else targets
for i, (sid, base, fdur) in enumerate(todo):
    query, _parts = build_query(base)
    ftoks = tokens(query)
    if not ftoks:
        out[sid] = {'basename': base, 'error': 'no-query'}
        continue
    fnum = scene_num(base)
    cands = []
    for s in sdb_search(query):
        sc, dm, ov = score(s, fdur, ftoks, fnum)
        cands.append({'box': 'stashdb', 'sid': s.get('id'), 'title': s.get('title'),
                      'date': s.get('date'), 'duration': s.get('duration'),
                      'studio': (s.get('studio') or {}).get('name'),
                      'performers': [p['performer']['name'] for p in (s.get('performers') or [])],
                      'score': sc, 'dur_match': dm, 'overlap': ov})
    for s in tpdb_search(query):
        sc, dm, ov = score(s, fdur, ftoks, fnum)
        cands.append({'box': 'tpdb', 'sid': s.get('remote_site_id'), 'title': s.get('title'),
                      'date': s.get('date'), 'duration': s.get('duration'),
                      'studio': (s.get('studio') or {}).get('name'),
                      'performers': [p['name'] for p in (s.get('performers') or [])],
                      'tags': [t2['name'] for t2 in (s.get('tags') or [])],
                      'score': sc, 'dur_match': dm, 'overlap': ov})
    cands.sort(key=lambda c: -c['score'])
    rec = cands[0] if cands and ((cands[0]['dur_match'] and cands[0]['overlap'] >= 0.35)
                                 or cands[0]['score'] >= 85) else None
    out[sid] = {'basename': base, 'query': query, 'fdur': fdur,
                'recommend': rec, 'top': cands[:3]}
    if (i+1) % 25 == 0:
        print(f'{i+1}/{len(todo)} ({time.time()-t:.0f}s)', flush=True)

ts = time.strftime('%Y%m%d_%H%M%S')
dest = os.path.join(EXP, f'unmatched-scene-search-{ts}.json')
json.dump(out, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
recs = sum(1 for v in out.values() if v.get('recommend'))
print(f'done: {len(out)} searched, {recs} confident recommendations -> {dest}')
