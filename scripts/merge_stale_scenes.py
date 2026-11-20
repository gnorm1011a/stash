"""Phase 3: merge stale scenes into their matched new scenes.

For each (stale_id -> new_id) pair, builds values = union of stale+dest
metadata (scalars prefer stale/curated when set; lists unioned; stash_ids
deduped by endpoint) and calls sceneMerge with play_history+o_history.

Usage: merge_stale_scenes.py [--limit N] [--offset N] [--dry]
"""
import json, os, sys, time, urllib.request, glob

GQL = 'http://192.168.0.31:9999/graphql'
REPO = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash'
EXPORTS = os.path.join(REPO, 'exports')

LIMIT = OFFSET = 0
DRY = '--dry' in sys.argv
for i, a in enumerate(sys.argv):
    if a == '--limit': LIMIT = int(sys.argv[i+1])
    if a == '--offset': OFFSET = int(sys.argv[i+1])

def gql(q, timeout=120):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    resp = json.load(urllib.request.urlopen(r, timeout=timeout))
    if 'errors' in resp:
        raise RuntimeError(resp['errors'])
    return resp

FLDS = '''id title code details director url urls date rating100 organized
studio{id} performers{id} tags{id} galleries{id}
groups{group{id} scene_index} movies{movie{id} scene_index}
stash_ids{endpoint stash_id} play_count o_counter resume_time play_duration'''

def scene(sid):
    r = gql('{findScene(id:"%d"){%s}}' % (sid, FLDS))
    return r['data']['findScene']

def esc(s):
    return json.dumps(s)  # handles quotes/unicode

def build_values(stale, dest, conflicts):
    v = {'id': str(dest['id'])}
    # scalars: prefer stale non-empty; log when both non-empty and differ
    for k in ('title', 'code', 'details', 'director', 'date', 'url'):
        sv, dv = stale.get(k), dest.get(k)
        if sv and dv and sv != dv:
            conflicts.append({'field': k, 'stale': sv, 'dest': dv, 'chose': 'stale'})
        if sv:
            v[k] = sv
    if stale.get('rating100'):
        if dest.get('rating100') and dest['rating100'] != stale['rating100']:
            conflicts.append({'field': 'rating100', 'stale': stale['rating100'], 'dest': dest['rating100'], 'chose': 'stale'})
        v['rating100'] = stale['rating100']
    if stale.get('organized') and not dest.get('organized'):
        v['organized'] = True
    if stale.get('resume_time'):
        v['resume_time'] = stale['resume_time']
    if stale.get('play_duration') and not dest.get('play_duration'):
        v['play_duration'] = stale['play_duration']
    # urls union
    urls = list(dict.fromkeys((stale.get('urls') or []) + (dest.get('urls') or [])))
    if stale.get('url') and stale['url'] not in urls:
        urls.insert(0, stale['url'])
    if urls:
        v['urls'] = urls
    # studio
    if stale.get('studio'):
        v['studio_id'] = str(stale['studio']['id'])
    # list unions
    def ids(objs):
        return [str(o['id']) for o in (objs or [])]
    v['performer_ids'] = list(dict.fromkeys(ids(stale.get('performers')) + ids(dest.get('performers'))))
    v['tag_ids'] = list(dict.fromkeys(ids(stale.get('tags')) + ids(dest.get('tags'))))
    v['gallery_ids'] = list(dict.fromkeys(ids(stale.get('galleries')) + ids(dest.get('galleries'))))
    # groups/movies union by id, prefer stale scene_index on conflict
    for fld, key, inp in (('groups', 'group', 'group_id'), ('movies', 'movie', 'movie_id')):
        merged = {}
        for e in (dest.get(fld) or []):
            merged[str(e[key]['id'])] = e.get('scene_index')
        for e in (stale.get(fld) or []):
            merged[str(e[key]['id'])] = e.get('scene_index')
        if merged:
            v[fld] = [{inp: gid, 'scene_index': idx} for gid, idx in merged.items() if gid != 'None']
    # stash_ids union deduped by (endpoint, stash_id); same endpoint diff id -> prefer stale, log
    by_ep = {}
    for s in (dest.get('stash_ids') or []):
        by_ep.setdefault(s['endpoint'], {})[s['stash_id']] = 'dest'
    for s in (stale.get('stash_ids') or []):
        ep, sid2 = s['endpoint'], s['stash_id']
        if ep in by_ep and sid2 not in by_ep[ep]:
            conflicts.append({'field': 'stash_ids', 'endpoint': ep, 'dest_ids': list(by_ep[ep]), 'stale_id': sid2, 'chose': 'stale'})
            del by_ep[ep]
        by_ep.setdefault(ep, {})[sid2] = 'stale'
    if by_ep:
        v['stash_ids'] = [{'endpoint': ep, 'stash_id': sid2}
                          for ep, ids_ in by_ep.items() for sid2 in ids_]
    return v

def gql_literal(obj):
    """Serialise a python dict/list/scalar as a GraphQL input literal."""
    if obj is None: return 'null'
    if obj is True: return 'true'
    if obj is False: return 'false'
    if isinstance(obj, (int, float)): return str(obj)
    if isinstance(obj, str): return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list): return '[' + ','.join(gql_literal(x) for x in obj) + ']'
    return '{' + ','.join(f'{k}:{gql_literal(val)}' for k, val in obj.items()) + '}'

# ---------- pairs ----------
m = json.load(open(sorted(glob.glob(os.path.join(EXPORTS, 'migration-match-*.json')))[-1], encoding='utf-8'))
pairs = [(x['stale_id'], x['new_id']) for x in m['matched']]
pairs += [(22820,25596),(22822,25603),(22827,25692),(22828,25694),(22839,25877),
          (23038,26499),(23109,25464),(23490,25447),(23818,25597),(23563,25970)]
pairs = pairs[OFFSET:OFFSET + LIMIT if LIMIT else None]
print(f'{len(pairs)} merges to run (dry={DRY})')

log = []
ok = fail = 0
for i, (stale_id, new_id) in enumerate(pairs):
    try:
        st, ds = scene(stale_id), scene(new_id)
        if not st:
            log.append({'stale_id': stale_id, 'new_id': new_id, 'result': 'stale-scene-gone'})
            continue
        if not ds:
            log.append({'stale_id': stale_id, 'new_id': new_id, 'result': 'dest-gone'})
            continue
        conflicts = []
        values = build_values(st, ds, conflicts)
        if DRY:
            log.append({'stale_id': stale_id, 'new_id': new_id, 'result': 'dry',
                        'values': values, 'conflicts': conflicts})
            continue
        mut = ('mutation{sceneMerge(input:{source:["%d"],destination:"%d",'
               'values:%s,play_history:true,o_history:true}){id}}'
               % (stale_id, new_id, gql_literal(values)))
        gql(mut)
        ok += 1
        log.append({'stale_id': stale_id, 'new_id': new_id, 'result': 'merged',
                    'values': values, 'conflicts': conflicts})
        if (i + 1) % 50 == 0:
            print(f'{i+1}/{len(pairs)} merged', flush=True)
    except Exception as e:
        fail += 1
        log.append({'stale_id': stale_id, 'new_id': new_id, 'result': 'error', 'error': str(e)[:400]})

ts = time.strftime('%Y%m%d_%H%M%S')
dest = os.path.join(EXPORTS, f'migration-merge-log-{ts}.json')
json.dump(log, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'merged={ok} failed={fail} logged={len(log)} -> {dest}')
