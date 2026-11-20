"""Fetch box art for ALL groups missing front_image.
Order: TPDB movies API (real box cover) -> StashDB scene image (fallback).
Conservative title matching; studio corroboration for extra-word titles.
"""
import json, os, re, sys, time, urllib.request, base64

EXP = r'M:\Files\Repositories\Personal\Stash\exports'
GQL = 'http://192.168.0.31:9999/graphql'
DRY = '--dry' in sys.argv

cfg = open(r'M:\Apps\stash\config\config.yml', encoding='utf-8').read()
TPDB_KEY = re.search(r'apikey:\s*(\S+)\s*\n\s*endpoint:\s*https://theporndb', cfg).group(1)
SDB_KEY = re.search(r'apikey:\s*(\S+)\s*\n\s*endpoint:\s*https://stashdb', cfg).group(1)

def gql(q):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    try:
        resp = json.load(urllib.request.urlopen(r, timeout=120))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read()[:300].decode(errors='replace'))
    if 'errors' in resp: raise RuntimeError(resp['errors'])
    return resp

def post(url, q, key=None):
    h = {'Content-Type': 'application/json'}
    if key: h['ApiKey'] = key
    r = urllib.request.Request(url, data=json.dumps({'query': q}).encode(), headers=h)
    try:
        return json.load(urllib.request.urlopen(r, timeout=60))
    except Exception:
        return {}

def tpdb_movies(q):
    r = urllib.request.Request('https://api.theporndb.net/movies?q=' + urllib.parse.quote(q),
        headers={'Authorization': 'Bearer ' + TPDB_KEY, 'Accept': 'application/json',
                 'User-Agent': 'Mozilla/5.0'})
    try:
        return json.load(urllib.request.urlopen(r, timeout=30)).get('data', [])
    except Exception:
        return []

def sdb_scenes(q):
    r = post('https://stashdb.org/graphql',
             '{searchScenes(term:%s,per_page:25){scenes{id title studio{name} images{url}}}}'
             % json.dumps(q), SDB_KEY)
    return (r.get('data') or {}).get('searchScenes', {}).get('scenes', [])

STOP = set('a an and the of in on at for to with from by'.split())
def toks(s):
    return {t for t in re.findall(r'[a-z0-9]+', (s or '').lower()) if t not in STOP}
def edition_digits(s):
    t = re.findall(r'[a-z0-9#]+', (s or '').lower())
    out = set()
    for i, tok in enumerate(t):
        if not tok.isdigit(): continue
        prev = t[i-1] if i else ''
        if prev in ('scene','ep','episode','chapter'): continue
        out.add(str(int(tok)))
    return out
def fetch_b64(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=60).read()
        ct = 'image/png' if data[:4] == b'\x89PNG' else ('image/webp' if data[:4] == b'RIFF' else 'image/jpeg')
        return 'data:%s;base64,%s' % (ct, base64.b64encode(data).decode()), len(data)
    except Exception:
        return None, 0

STRUCT = {'scene','ep','episode','part','vol','chapter','vols','pts'}
def studio_toks(name):
    return toks(re.sub(r'(?i)\b(video|videos|productions?|pictures|films?|entertainment|media|inc|llc)\b','',name or ''))

# fetch all image-less groups, paged
missing = []
page = 1
while True:
    r = gql('{findGroups(group_filter:{is_missing:"front_image"},filter:{per_page:200,page:%d})'
            '{groups{id name studio{name}} count}}' % page)
    fg = r['data']['findGroups']
    missing += fg['groups']
    if len(missing) >= fg['count']: break
    page += 1
print(len(missing), 'groups missing front_image', file=sys.stderr)

ok_tpdb = ok_sdb = miss = errs = 0
log = []
for i, g in enumerate(missing):
    name = g['name']
    mtoks, mdig = toks(name), edition_digits(name)
    gstudio = (g.get('studio') or {}).get('name')
    entry = {'group': name, 'gid': g['id']}
    front = back = src = mtitle = None
    # --- TPDB movies ---
    best = None
    for m in tpdb_movies(name):
        ct, cd = toks(m.get('title')), edition_digits(m.get('title') or '')
        if not (mtoks <= ct) or (mdig != cd and (mdig or cd)):
            continue
        extra = {t for t in ct - mtoks if not t.isdigit() and t not in STRUCT}
        site = m.get('site') or {}
        sname = site.get('name') if isinstance(site, dict) else ''
        sok = gstudio and sname and studio_toks(sname) == studio_toks(gstudio)
        if extra and not sok: continue
        best = m; break
    if best:
        front = best.get('image') or (best.get('posters') or {}).get('large')
        back = best.get('back_image') or (best.get('background_back') or {}).get('large')
        src, mtitle = 'tpdb', best.get('title')
    else:
        # --- StashDB fallback ---
        for s in sdb_scenes(name):
            ct, cd = toks(s.get('title')), edition_digits(s.get('title') or '')
            if not (mtoks <= ct) or (mdig != cd and (mdig or cd)): continue
            extra = {t for t in ct - mtoks if not t.isdigit() and t not in STRUCT}
            sname = (s.get('studio') or {}).get('name')
            sok = gstudio and sname and studio_toks(sname) == studio_toks(gstudio)
            if extra and not sok: continue
            if s.get('images'):
                front, src, mtitle = s['images'][0]['url'], 'stashdb', s.get('title')
            break
    if not front:
        entry['result'] = 'no-cover'; miss += 1; log.append(entry); continue
    import difflib
    _a=''.join(c for c in name.lower() if c.isalnum())
    _b=''.join(c for c in (mtitle or '').lower() if c.isalnum())
    if difflib.SequenceMatcher(None,_a,_b).ratio() < 0.70:
        entry['result']='skipped-low-sim'; entry['match']=mtitle; miss+=1; log.append(entry); continue
    if DRY:
        entry.update(result='dry', source=src, match=mtitle, front=front[:100])
        log.append(entry); ok_tpdb += src == 'tpdb'; ok_sdb += src == 'stashdb'; continue
    try:
        fields = {'id': g['id']}
        fb, fsz = fetch_b64(front)
        if fb: fields['front_image'] = fb
        bb, bsz = fetch_b64(back) if back else (None, 0)
        if bb: fields['back_image'] = bb
        if len(fields) > 1:
            gql('mutation{groupUpdate(input:%s){id}}' % ('{' + ','.join(f'{k}:' + (json.dumps(v) if isinstance(v,str) else str(v)) for k,v in fields.items()) + '}'))
            entry.update(result='cover-set', source=src, match=mtitle, fsz=fsz, bsz=bsz)
            if src == 'tpdb': ok_tpdb += 1
            else: ok_sdb += 1
        else:
            entry['result'] = 'img-fetch-fail'
    except Exception as e:
        entry['result'] = 'error'; entry['error'] = str(e)[:200]; errs += 1
    log.append(entry)
    if i % 25 == 0: print(i, '/', len(missing), file=sys.stderr)

json.dump(log, open(os.path.join(EXP, 'group-covers-all-log.json'), 'w', encoding='utf-8'), indent=1)
print('tpdb:', ok_tpdb, '| stashdb:', ok_sdb, '| no cover:', miss, '| errors:', errs, '| dry:', DRY)
