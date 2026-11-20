"""Check-1: performer-name analysis of unmatched (unidentified) scenes.

For each scene that got no stash_id from Identify, parse filename segments
and match candidate performer names against the local performer DB
(names + aliases). Output: exports/unmatched-performer-analysis.csv
"""
import csv, json, os, re, urllib.request
from difflib import SequenceMatcher

GQL = 'http://192.168.0.31:9999/graphql'
REPO = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash'
EXP = os.path.join(REPO, 'exports')

def gql(q):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    for a in range(4):
        try:
            return json.load(urllib.request.urlopen(r, timeout=120))
        except Exception:
            if a == 3: raise
            import time; time.sleep(8)

# ---- performer index: name + aliases -> canonical ----
perf = json.load(open(os.path.join(EXP, 'performers.json'), encoding='utf-8-sig'))
names = {}   # norm -> (canonical, id)
for p in perf['data']['allPerformers']:
    canon = ' '.join(p['name'].split())
    for n in [canon] + [' '.join(a.split()) for a in (p['alias_list'] or [])]:
        names.setdefault(n.lower(), []).append((canon, p['id']))
print(len(names), 'name/alias keys for', len(perf['data']['allPerformers']), 'performers')

# ---- unmatched targets: identify set minus scenes that now have stash_ids ----
ids = json.load(open(os.path.join(EXP, 'identify-target-ids.json')))
targets = []
for i in range(0, len(ids), 100):
    parts = ' '.join('s%d:findScene(id:"%d"){id stash_ids{stash_id} files{basename}}' % (i2, i2) for i2 in ids[i:i+100])
    r = gql('{' + parts + '}')
    for s in r['data'].values():
        if s and not s['stash_ids'] and s['files']:
            targets.append((int(s['id']), s['files'][0]['basename']))
print(len(targets), 'unmatched scenes to analyse')

STOP = {'ui', 'dvd', 'xxx', 'dvdrip', 'hd', 'ts', 'rm', 'compilation', 'amateur',
        'teen', 'asian', 'euro', 'russian', 'thai', 'latina', 'ebony', 'milf'}
def segs(base):
    b = os.path.splitext(base)[0]
    b = re.sub(r'\([^)]*\)\s*$', '', b)          # trailing (res)
    b = re.sub(r'\[[^\]]*\]', ' ', b)            # [junk]
    b = re.sub(r'\{[^}]*\}', ' ', b)             # {studio}
    b = re.sub(r'[-–]\(|\)\s*$', ' ', b)
    b = re.sub(r'\s*-\([^)]*\).*', '', b)        # -(names)-{x}-[tags] tail
    out = []
    for s in b.split(' - '):
        s = ' '.join(s.split()).strip(' -._')
        if s and s.lower() not in STOP and len(s) > 2:
            out.append(s)
    return out

def match(seg):
    key = seg.lower()
    if key in names:
        return [(c, 'exact', 100) for c in names[key]]
    # leading-word variant (e.g. "Yuki Mor" -> "Yuki Mori")
    best = []
    for n, cs in names.items():
        if abs(len(n) - len(key)) <= 3 and (n.startswith(key) or key.startswith(n)):
            best += [(c, 'prefix', 95) for c in cs]
    if best:
        return best
    for n, cs in names.items():
        ratio = SequenceMatcher(None, key, n).ratio()
        if ratio >= 0.88:
            best += [(c, 'fuzzy', round(ratio * 100)) for c in cs]
    return sorted(best, key=lambda x: -x[2])[:3]

rows = []
stats = {'exact': 0, 'fuzzy_only': 0, 'none': 0}
for sid, base in targets:
    found, checked = [], []
    for seg in segs(base):
        checked.append(seg)
        for canon, how, conf in match(seg):
            found.append((seg, canon, how, conf))
    if found:
        ex = [f for f in found if f[2] == 'exact']
        stats['exact' if ex else 'fuzzy_only'] += 1
    else:
        stats['none'] += 1
    rec = '; '.join(f'{c} (as "{s}", {h} {cf}%)' for s, c, h, cf in found[:4])
    rows.append([sid, base, rec, ' | '.join(checked)])

out = os.path.join(EXP, 'unmatched-performer-analysis.csv')
with open(out, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['scene_id', 'filename', 'performer_candidates', 'segments_checked'])
    w.writerows(rows)
print(stats, '->', out)
