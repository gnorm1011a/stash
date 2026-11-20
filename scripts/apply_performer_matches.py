"""Apply exact-match performer assignments to unmatched scenes.
Reads unmatched-performer-analysis.csv, takes only 'exact' hits,
unions with existing scene performers, sceneUpdate per scene.
"""
import ast, csv, json, os, re, sys, urllib.request

GQL = 'http://192.168.0.31:9999/graphql'
CSV = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash\exports\unmatched-performer-analysis.csv'
DRY = '--dry' in sys.argv

def gql(q):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    resp = json.load(urllib.request.urlopen(r, timeout=60))
    if 'errors' in resp:
        raise RuntimeError(resp['errors'])
    return resp

rows = list(csv.reader(open(CSV, encoding='utf-8')))[1:]
targets = {}   # scene_id -> {performer ids}
for sid, fname, rec, segs in rows:
    if 'exact' not in rec:
        continue
    pids = set()
    for t in re.findall(r"\(([^)]*'exact'[^)]*)\)", 'x'):  # placeholder; parse below
        pass
    # rec entries look like: ('Name', 'id') (as "seg", exact 100%)
    for m in re.finditer(r"\('([^']*)',\s*'(\d+)'\)\s*\(as\s+\"[^\"]*\",\s*exact\s+\d+%\)", rec):
        pids.add(m.group(2))
    if pids:
        targets[int(sid)] = pids
print(len(targets), 'scenes to update')

ok = fail = 0
log = []
for sid, pids in targets.items():
    r = gql('{findScene(id:"%d"){performers{id}}}' % sid)
    cur = {p['id'] for p in r['data']['findScene']['performers']}
    union = sorted(cur | pids, key=int)
    if union == sorted(cur, key=int):
        log.append({'id': sid, 'result': 'already-present'})
        continue
    if DRY:
        log.append({'id': sid, 'result': 'dry', 'add': sorted(pids - cur, key=int)})
        continue
    mut = 'mutation{sceneUpdate(input:{id:"%d",performer_ids:[%s]}){id}}' % (
        sid, ','.join('"%s"' % p for p in union))
    try:
        gql(mut)
        ok += 1
        log.append({'id': sid, 'result': 'ok', 'added': sorted(pids - cur, key=int)})
    except Exception as e:
        fail += 1
        log.append({'id': sid, 'result': 'error', 'error': str(e)[:300]})

out = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash\exports\performer-apply-log.json'
json.dump(log, open(out, 'w', encoding='utf-8'), indent=1)
print('updated', ok, '| failed', fail, '| logged', len(log), '->', out)
