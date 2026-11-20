"""Group-creation proposal: cluster group-less scenes by DVD/movie title,
fetch each movie's StashDB scene list, match files by Scene N + duration.
Read-only -- writes exports/group-proposal.json. No mutations.
"""
import json, os, re, sys, time, urllib.request, glob
from collections import defaultdict

EXP = r'M:\Files\Repositories\Personal\Stash\exports'
GQL = 'http://192.168.0.31:9999/graphql'
SDB = 'https://stashdb.org/graphql'

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

STOP = set('a an and the of in on at for to with from by'.split())
def toks(s):
    return {t for t in re.findall(r'[a-z0-9]+', (s or '').lower()) if t not in STOP}
def scene_num(s):
    m = re.search(r'(?i)scene\s*(\d+)', s or '')
    return int(m.group(1)) if m else None
def edition_digits(s):
    t = re.findall(r'[a-z0-9#]+', (s or '').lower())
    out = set()
    for i, tok in enumerate(t):
        if not tok.isdigit(): continue
        prev = t[i-1] if i else ''
        if prev in ('scene','ep','episode','part','vol','chapter','#'): continue
        out.add(str(int(tok)))
    return out

scope = json.load(open(os.path.join(EXP, 'group-scope.json')))
d = json.load(open(sorted(glob.glob(os.path.join(EXP, 'unmatched-scene-search-*.json')))[-1], encoding='utf-8'))
nogroup = [s for s in scope if scope[s] and not scope[s]['groups'] and d.get(s)]

by_title = defaultdict(list)
for s in nogroup:
    if d[s].get('query'):
        by_title[d[s]['query'].lower()].append(s)
print(len(nogroup), 'group-less scenes |', len(by_title), 'distinct titles')

def sdb_scenes(title):
    r = post(SDB, '{searchScenes(term:%s,per_page:40){scenes{id title date duration '
                  'studio{name} urls{url} images{url} '
                  'performers{performer{name}}}}}' % json.dumps(title), SDB_KEY)
    return (r.get('data') or {}).get('searchScenes', {}).get('scenes', [])

proposals = []
t0 = time.time()
for i, (tkey, sids) in enumerate(by_title.items()):
    rec0 = d[sids[0]]
    q = rec0['query']
    mtoks = toks(q); mdig = edition_digits(q)
    pool = []
    for s in sdb_scenes(q):
        ct = toks(s.get('title'))
        cd = edition_digits(s.get('title'))
        # same movie: all movie tokens present AND edition digits agree
        if mtoks <= ct and (mdig <= cd if mdig else not cd):
            pool.append(s)
    if not pool:
        proposals.append({'movie': q, 'files': len(sids), 'indexed': 0, 'members': []})
        continue
    # studio = mode of pool studios
    stud = {}
    for c in pool:
        n = (c.get('studio') or {}).get('name')
        if n: stud[n] = stud.get(n, 0) + 1
    studio = max(stud, key=stud.get) if stud else None
    dates = sorted(c['date'] for c in pool if c.get('date'))
    members = []
    for sid in sids:
        rec = d[sid]
        fnum, fdur = scene_num(rec['basename']), rec.get('fdur')
        best = None; tier = None
        for c in pool:
            cnum = scene_num(c['title'])
            dur_ok = c.get('duration') and fdur and abs(c['duration'] - fdur) <= 12
            if fnum and cnum == fnum and dur_ok: tier = 'exact'; best = c; break
            if fnum and cnum == fnum and not dur_ok: best = best or c; tier = tier or 'scene-only'
            elif dur_ok and not best: best = c; tier = 'duration'
        members.append({'id': sid, 'basename': rec['basename'], 'scene_num': fnum,
                        'fdur': fdur, 'match': tier,
                        'box_title': best['title'] if best else None,
                        'box_sid': best['id'] if best else None,
                        'box_dur': best.get('duration') if best else None,
                        'performers': [p['performer']['name'] for p in (best.get('performers') or [])] if best else [],
                        'scene_index': fnum})
    cover = None
    for c in pool:
        if c.get('images'):
            cover = c['images'][0]['url']; break
    url = None
    for c in pool:
        if c.get('urls'):
            url = c['urls'][0]['url']; break
    proposals.append({'movie': q, 'files': len(sids), 'indexed': len(pool),
                      'studio': studio, 'date': dates[0] if dates else None,
                      'cover': cover, 'url': url, 'members': members})
    if i % 30 == 0:
        print(i, '/', len(by_title), f'{time.time()-t0:.0f}s', file=sys.stderr)

proposals.sort(key=lambda p: -p['indexed'])
json.dump(proposals, open(os.path.join(EXP, 'group-proposal.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
idx = sum(1 for p in proposals if p['indexed'])
exact = sum(1 for p in proposals for m in p['members'] if m['match'] == 'exact')
sonly = sum(1 for p in proposals for m in p['members'] if m['match'] == 'scene-only')
durn  = sum(1 for p in proposals for m in p['members'] if m['match'] == 'duration')
print('titles with StashDB scenes:', idx, '/', len(proposals))
print('member matches — exact:', exact, '| scene-only:', sonly, '| duration:', durn,
      '| unmatched:', sum(p['files'] for p in proposals) - exact - sonly - durn)
