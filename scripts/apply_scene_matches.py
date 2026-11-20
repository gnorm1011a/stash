"""Apply Tier-A stash-box scene matches to unmatched scenes.

For each approved scene->candidate pair: resolve studio + performers to local
records (create stubs for missing), then sceneUpdate with
title/date/studio/performers/tags + stash_ids. MERGE semantics: lists unioned.
"""
import json, os, re, sys, time, urllib.request, glob

GQL = 'http://192.168.0.31:9999/graphql'
REPO = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash'
EXP = os.path.join(REPO, 'exports')
DRY = '--dry' in sys.argv

def gql(q):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    resp = json.load(urllib.request.urlopen(r, timeout=90))
    if 'errors' in resp:
        raise RuntimeError(resp['errors'])
    return resp

# local performer + studio indexes
perf = json.load(open(os.path.join(EXP, 'performers.json'), encoding='utf-8-sig'))
PNAMES = {}
for p in perf['data']['allPerformers']:
    canon = ' '.join(p['name'].split())
    for n in [canon] + [' '.join(a.split()) for a in (p.get('alias_list') or [])]:
        PNAMES.setdefault(n.lower(), p['id'])

def norm_name(n):
    return ' '.join((n or '').split())

def local_perf(name):
    return PNAMES.get(norm_name(name).lower())

def create_performer(name):
    r = gql('mutation{performerCreate(input:{name:%s}){id}}' % json.dumps(norm_name(name)))
    return r['data']['performerCreate']['id']

_studio_cache = {}
def local_studio(name):
    if not name: return None
    key = norm_name(name).lower()
    if key in _studio_cache: return _studio_cache[key]
    r = gql('{findStudios(studio_filter:{name:{value:%s,modifier:EQUALS}}){studios{id}}}'
            % json.dumps(name))
    ids = [s['id'] for s in r['data']['findStudios']['studios']]
    if ids:
        _studio_cache[key] = ids[0]
        return ids[0]
    r = gql('{findStudios(studio_filter:{name:{value:%s,modifier:INCLUDES}}){studios{id name}}}'
            % json.dumps(name))
    for s in r['data']['findStudios']['studios']:
        if s['name'].lower() == key:
            _studio_cache[key] = s['id']
            return s['id']
    if DRY:
        return 'NEW'
    r = gql('mutation{studioCreate(input:{name:%s}){id}}' % json.dumps(norm_name(name)))
    _studio_cache[key] = r['data']['studioCreate']['id']
    return _studio_cache[key]

_tag_cache = {}
def local_tag(name):
    key = norm_name(name).lower()
    if key in _tag_cache: return _tag_cache[key]
    r = gql('{findTags(tag_filter:{name:{value:%s,modifier:EQUALS}}){tags{id}}}'
            % json.dumps(name))
    ids = [t['id'] for t in r['data']['findTags']['tags']]
    if ids:
        _tag_cache[key] = ids[0]
        return ids[0]
    if DRY:
        return 'NEW'
    try:
        r = gql('{findTags(tag_filter:{aliases:{value:%s,modifier:INCLUDES}}){tags{id}}}'
                % json.dumps(name))
        ids = [t['id'] for t in r['data']['findTags']['tags']]
        if ids:
            _tag_cache[key] = ids[0]
            return ids[0]
    except Exception:
        pass
    try:
        r = gql('mutation{tagCreate(input:{name:%s}){id}}' % json.dumps(norm_name(name)))
        _tag_cache[key] = r['data']['tagCreate']['id']
        return _tag_cache[key]
    except Exception:
        _tag_cache[key] = None
        return None

def lit(v):
    if isinstance(v, list):
        return '[' + ','.join(lit(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{' + ','.join(f'{k}:{lit(x)}' for k, x in v.items()) + '}'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(v, ensure_ascii=False)

# inputs
search_file = sorted(glob.glob(os.path.join(EXP, 'unmatched-scene-search-*.json')))[-1]
d = json.load(open(search_file, encoding='utf-8'))
tiers = json.load(open(os.path.join(EXP, 'scene-search-tiers.json')))
BOX_URL = {'stashdb': 'https://stashdb.org/graphql', 'tpdb': 'https://theporndb.net/graphql'}

TIER = 'B' if '--tier' in sys.argv and sys.argv[sys.argv.index('--tier')+1] == 'B' else 'A'
REVIEW_TAG = '1001'
if TIER == 'B':
    items = [(e['id'], e.get('why')) for e in tiers['B']]
else:
    items = [(sid, None) for sid in tiers['A']]

ok = fail = 0
log = []
for sid, why in items:
    rec = d[str(sid)]['recommend']
    # resolve performers
    pids = []
    for name in rec.get('performers') or []:
        pid = local_perf(name)
        if not pid and not DRY and TIER != 'B':
            try:
                pid = create_performer(name)
            except Exception:
                pid = None
        if pid:
            pids.append(pid)
    stid = local_studio(rec.get('studio'))
    tids = [local_tag(t) for t in rec.get('tags') or []]
    tids = [t for t in tids if t and t != 'NEW']
    # union with existing scene state
    r = gql('{findScene(id:"%s"){performers{id} tags{id} stash_ids{endpoint stash_id}}}' % sid)
    sc = r['data']['findScene']
    cur_p = {p['id'] for p in sc['performers']}
    cur_t = {t['id'] for t in sc['tags']}
    cur_s = sc['stash_ids']
    pids = sorted(cur_p | set(pids), key=int)
    if TIER == 'B':
        tids.append(REVIEW_TAG)
    tids = sorted(cur_t | set(tids), key=int)
    ep = BOX_URL[rec['box']]
    stash_ids = cur_s + ([{'endpoint': ep, 'stash_id': rec['sid']}]
                         if rec['sid'] and not any(s['endpoint'] == ep for s in cur_s) else [])
    fields = {'id': str(sid), 'performer_ids': pids, 'stash_ids': stash_ids}
    if rec.get('title'): fields['title'] = rec['title']
    if rec.get('date'): fields['date'] = rec['date']
    if stid and stid != 'NEW': fields['studio_id'] = stid
    if tids: fields['tag_ids'] = tids
    if DRY:
        log.append({'id': sid, 'why': why, 'fields': fields, 'rec': rec})
        continue
    mut = 'mutation{sceneUpdate(input:%s){id}}' % ('{' + ','.join(
        f'{k}:{lit(v)}' for k, v in fields.items()) + '}')
    try:
        gql(mut)
        ok += 1
        log.append({'id': sid, 'why': why, 'result': 'ok', 'fields': fields})
    except Exception as e:
        fail += 1
        log.append({'id': sid, 'why': why, 'result': 'error', 'error': str(e)[:300]})

out = os.path.join(EXP, 'scene-search-apply-log-tier%s.json' % TIER.lower())
json.dump(log, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('applied', ok, '| failed', fail, '| dry', len(log) if DRY else 0)
