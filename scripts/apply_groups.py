"""Create Stash groups for scope-B movie clusters (multi-file OR StashDB-indexed),
attach member scenes with scene_index, enrich indexed groups with
studio/date/url/cover, apply exact-match performers + stash_ids, tag
weaker matches 'review'. Hooks must be disabled before running."""
import json, os, re, sys, time, urllib.request, base64

EXP = r'M:\Files\Repositories\Personal\Stash\exports'
GQL = 'http://192.168.0.31:9999/graphql'
DRY = '--dry' in sys.argv
REVIEW = '1001'

def gql(q):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    try:
        resp = json.load(urllib.request.urlopen(r, timeout=120))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read()[:300].decode(errors='replace'))
    if 'errors' in resp: raise RuntimeError(resp['errors'])
    return resp

def lit(v):
    if isinstance(v, list): return '[' + ','.join(lit(x) for x in v) + ']'
    if isinstance(v, dict): return '{' + ','.join(f'{k}:{lit(x)}' for k, x in v.items()) + '}'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return str(v)
    return json.dumps(v, ensure_ascii=False)

perf = json.load(open(os.path.join(EXP, 'performers.json'), encoding='utf-8-sig'))
PNAMES = {}
for p in perf['data']['allPerformers']:
    for n in [p['name']] + (p.get('alias_list') or []):
        PNAMES.setdefault(' '.join(n.split()).lower(), p['id'])

def local_perf(n): return PNAMES.get(' '.join(n.split()).lower())
def create_perf(n):
    try:
        r = gql('mutation{performerCreate(input:{name:%s}){id}}' % json.dumps(' '.join(n.split())))
        PNAMES[' '.join(n.split()).lower()] = r['data']['performerCreate']['id']
        return r['data']['performerCreate']['id']
    except Exception:
        # stale local index -- look up live
        r = gql('{findPerformers(performer_filter:{name:{value:%s,modifier:EQUALS}}){performers{id}}}' % json.dumps(n))
        p = r['data']['findPerformers']['performers']
        if p:
            PNAMES[' '.join(n.split()).lower()] = p[0]['id']
            return p[0]['id']
        return None

_sg = {}
def studio_id(name):
    if not name: return None
    k = ' '.join(name.split()).lower()
    if k in _sg: return _sg[k]
    r = gql('{findStudios(studio_filter:{name:{value:%s,modifier:EQUALS}}){studios{id}}}' % json.dumps(name))
    ids = [s['id'] for s in r['data']['findStudios']['studios']]
    if ids: _sg[k] = ids[0]; return ids[0]
    if DRY: _sg[k] = 'NEW'; return 'NEW'
    r = gql('mutation{studioCreate(input:{name:%s}){id}}' % json.dumps(name))
    _sg[k] = r['data']['studioCreate']['id']; return _sg[k]

def find_group(name):
    r = gql('{findGroups(group_filter:{name:{value:%s,modifier:EQUALS}}){groups{id name}}}' % json.dumps(name))
    for g in r['data']['findGroups']['groups']:
        if g['name'].lower() == name.lower(): return g['id']
    return None

def fetch_b64(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=60).read()
        ct = 'image/jpeg'
        if data[:4] == b'\x89PNG': ct = 'image/png'
        elif data[:4] == b'RIFF': ct = 'image/webp'
        return 'data:%s;base64,%s' % (ct, base64.b64encode(data).decode())
    except Exception:
        return None

props = json.load(open(os.path.join(EXP, 'group-proposal.json'), encoding='utf-8'))
import glob
sdb_data = json.load(open(sorted(glob.glob(os.path.join(EXP, 'unmatched-scene-search-*.json')))[-1], encoding='utf-8'))
def scene_num(s):
    m = re.search(r'(?i)scene\s*(\d+)', s or '')
    return int(m.group(1)) if m else None
# rebuild members for non-indexed proposals from the search export
scope = json.load(open(os.path.join(EXP, 'group-scope.json')))
from collections import defaultdict
by_title = defaultdict(list)
for sid in scope:
    if scope[sid] and not scope[sid]['groups'] and sdb_data.get(sid, {}).get('query'):
        by_title[sdb_data[sid]['query'].lower()].append(sid)
for p in props:
    if not p['members']:
        p['members'] = [{'id': s, 'basename': sdb_data[s]['basename'],
                         'scene_num': scene_num(sdb_data[s]['basename']),
                         'match': None, 'performers': []}
                        for s in by_title.get(p['movie'].lower(), [])]
        for m in p['members']:
            m['scene_index'] = m['scene_num']
todo = [p for p in props if p['files'] >= 2 or p['indexed'] > 0]
print(len(todo), 'groups to create/process')

created = joined = perf_applied = tagged = errs = 0
log = []
for p in todo:
    try:
        name = ' '.join(p['movie'].split())
        gid = find_group(name)
        if not gid:
            if DRY:
                gid = 'DRY'
            else:
                fields = {'name': name}
                sid_ = studio_id(p.get('studio'))
                if sid_ and sid_ != 'NEW': fields['studio_id'] = sid_
                if p.get('date'): fields['date'] = p['date']
                if p.get('url'): fields['urls'] = [p['url']]
                if p.get('cover'):
                    b64 = fetch_b64(p['cover'])
                    if b64: fields['front_image'] = b64
                mut = 'mutation{groupCreate(input:%s){id}}' % ('{' + ','.join(f'{k}:{lit(v)}' for k, v in fields.items()) + '}')
                gid = gql(mut)['data']['groupCreate']['id']
                created += 1
        for m in p['members']:
            try:
                r = gql('{findScene(id:"%s"){groups{group{id}} performers{id} tags{id} stash_ids{endpoint stash_id}}}' % m['id'])
                sc = r['data']['findScene']
                grp = {g['group']['id'] for g in sc['groups']}
                if DRY and gid == 'DRY':
                    grp = set()  # pretend new group for preview
                if gid != 'DRY' and gid in grp:
                    pass
                else:
                    gmem = [{'group_id': g, } for g in grp] + [{'group_id': gid}]
                    if m.get('scene_index'): gmem[-1]['scene_index'] = m['scene_index']
                    fields = {'id': str(m['id']), 'groups': gmem}
                    if m['match'] == 'exact':
                        pids = []
                        for n in m.get('performers') or []:
                            pid = local_perf(n) or (None if DRY else create_perf(n))
                            if pid: pids.append(pid)
                        fields['performer_ids'] = sorted({x['id'] for x in sc['performers']} | set(pids), key=int)
                        ep = 'https://stashdb.org/graphql'
                        sids = sc['stash_ids'] + ([{'endpoint': ep, 'stash_id': m['box_sid']}]
                            if m['box_sid'] and not any(x['endpoint'] == ep for x in sc['stash_ids']) else [])
                        fields['stash_ids'] = sids
                    if m['match'] in ('scene-only', 'duration'):
                        fields['tag_ids'] = sorted({t['id'] for t in sc['tags']} | {REVIEW}, key=int)
                        tagged += 1
                    if not DRY:
                        gql('mutation{sceneUpdate(input:%s){id}}' % ('{' + ','.join(f'{k}:{lit(v)}' for k, v in fields.items()) + '}'))
                    joined += 1
                    if m['match'] == 'exact': perf_applied += 1
                log.append({'group': name, 'scene': m['id'], 'match': m['match'], 'result': 'ok'})
            except Exception as e:
                errs += 1; log.append({'group': name, 'scene': m['id'], 'result': 'error', 'error': str(e)[:200]})
        log.append({'group': name, 'gid': gid, 'result': 'group-ok'})
    except Exception as e:
        errs += 1; log.append({'group': p['movie'], 'result': 'group-error', 'error': str(e)[:200]})

json.dump(log, open(os.path.join(EXP, 'group-apply-log.json'), 'w', encoding='utf-8'), indent=1)
print('groups-created:', created, '| scenes-joined:', joined, '| exact-perfs:', perf_applied,
      '| review-tagged:', tagged, '| errors:', errs, '| dry:', DRY)
