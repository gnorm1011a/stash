"""Phase 2: match stale scene records to post-scan scenes.

Reads the stale snapshot, builds old->new path chains from the rename/
conversion/move logs, and cross-checks each stale scene's missing path
against (a) disk, (b) current Stash scene inventory by file path.

Output: exports/migration-match-<ts>.json with per-scene classification:
  self_healed  - scene's file entry was repathed by scan (all files now exist)
  matched      - stale file maps to a different scene (merge candidate)
  multi        - stale scene had N files, maps to several new scenes (parts->one mp4)
  unmatched    - no new file found (genuinely deleted/missing -> clean)
  ambiguous    - multiple candidate scenes (dup names) -> manual review
"""
import json, os, re, sys, time, urllib.request, glob

GQL = 'http://192.168.0.31:9999/graphql'
REPO = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash'
EXPORTS = os.path.join(REPO, 'exports')
SNAP = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(EXPORTS, 'stale-snapshot-*.json')))[-1]

def to_nas(p):
    p = p.replace('\\', '/')
    p = re.sub(r'^//192\.168\.0\.31/', '/mnt/Nasferatu/', p)
    p = re.sub(r'^[Zz]:/', '/mnt/Nasferatu/Collection/', p)
    return p

def to_win(nas):
    p = nas.replace('/mnt/Nasferatu/', '//192.168.0.31/')
    return p.replace('/', '\\')

def gql(q, timeout=180):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    for attempt in range(5):
        try:
            return json.load(urllib.request.urlopen(r, timeout=timeout))
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode()
            if attempt == 4:
                raise RuntimeError(f'HTTP {e.code}: {body}')
            time.sleep(10)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(10)

def norm_base(b):
    b = os.path.splitext(b)[0].lower()
    return re.sub(r'\s+', ' ', b).strip()

def norm_path(p):
    return to_nas(p).lower()

# ---------- build old-name -> new-name maps from logs ----------
def load_json(p):
    return json.load(open(p, encoding='utf-8'))

def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]

# basename -> basename renames (root-level logs + oc logs applied before flatten)
renames = {}          # normalized old basename -> new basename
for f in ['rename-perf-typos-log.json', 'rename-safe-fixes-log.json',
          'rename-residual-spaces-log.json', 'rename-dup-flags-log.json',
          'oc-safe-fixes-log.json']:
    for e in load_json(os.path.join(EXPORTS, f)):
        if e.get('result') == 'renamed' and e.get('dst'):
            renames[norm_base(e['file'])] = e['dst']

# full-path renames (Unfiled->Video etc.) + conversion log src->dst
path_map = {}         # normalized old full path -> new full path (nas-normalized)
for e in load_jsonl(os.path.join(EXPORTS, 'rename-applied-log.json')):
    if e.get('src') and e.get('dst'):
        path_map[norm_path(e['src'])] = to_nas(e['dst'])
for e in load_jsonl(os.path.join(EXPORTS, 'wmv-convert-log.jsonl')):
    if e.get('src') and e.get('dst'):
        path_map[norm_path(e['src'])] = to_nas(e['dst'])
for e in load_jsonl(os.path.join(EXPORTS, 'oc-combine-log.jsonl')):
    # multi-part: src_dir/parts[i] -> out
    if not (e.get('src_dir') and e.get('out')):
        continue
    for part in e.get('parts', []):
        src = e['src_dir'] + '/' + part
        path_map[norm_path(src)] = to_nas(e['out'])

def chain(old_nas):
    """Return ordered candidate new NAS paths for a stale file path."""
    cands = []
    p = norm_path(old_nas)
    if p in path_map:
        cands.append(path_map[p])
    # basename rename
    base = os.path.basename(old_nas)
    nb = renames.get(norm_base(base))
    name = nb if nb else base
    # ext swap for legacy extensions
    stem, ext = os.path.splitext(name)
    names = [name]
    if ext.lower() in ('.wmv', '.avi', '.mpg', '.mpeg', '.f4v'):
        names.append(stem + '.mp4')
    # dir transforms
    d = os.path.dirname(to_nas(old_nas))
    for n in names:
        cands.append(d + '/' + n)                                  # same dir
        if '/Old Collection' in d:
            cands.append('/mnt/Nasferatu/Collection/Video/' + n)   # OC* -> root
    seen, out = set(), []
    for c in cands:
        k = norm_path(c)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out

# ---------- load stale snapshot ----------
snap = load_json(SNAP)
stale = snap['scenes']
print(f'snapshot: {len(stale)} scenes from {os.path.basename(SNAP)}')

# ---------- fetch current scene inventory (post-scan) ----------
print('fetching current scene inventory...')
inv = []      # (path, scene_id, size, duration)
page = 1
while True:
    r = gql('{findScenes(filter:{per_page:1000,page:%d}){count scenes{id files{path basename size duration}}}}' % page)
    fs = r['data']['findScenes']
    inv += [(f['path'], int(s['id']), f['size'], f['duration']) for s in fs['scenes'] for f in s['files']]
    if page * 1000 >= fs['count']:
        break
    page += 1
print(f'{len(inv)} file entries across inventory')

# file entries that are missing on disk (from snapshot) — exclude from indexes
missing_norm = set()
for s in stale:
    s['_missing_paths'] = list(dict.fromkeys(s['_missing_paths']))
    for mp in s['_missing_paths']:
        missing_norm.add(norm_path(mp))

by_path = {}
by_base = {}
for path, sid, size, dur in inv:
    k = norm_path(path)
    if k in missing_norm:
        continue  # stale entry — not a valid match target
    by_path.setdefault(k, []).append(sid)
    by_base.setdefault(norm_base(os.path.basename(path)), []).append((sid, k, size, dur))

# ---------- classify each stale scene ----------
results = {'self_healed': [], 'matched': [], 'multi': [], 'unmatched': [], 'ambiguous': []}
for s in stale:
    sid = int(s['id'])
    # self-heal check: does any current file of this scene exist on disk?
    cur = r = gql('{findScene(id:"%d"){files{path}}}' % sid)
    cur_files = cur['data']['findScene']['files'] if cur['data']['findScene'] else []
    if cur_files and all(os.path.exists(to_win(f['path'])) for f in cur_files):
        results['self_healed'].append(sid)
        continue

    matches = {}
    for mp in s['_missing_paths']:
        for cand in chain(mp):
            k = norm_path(cand)
            if os.path.exists(to_win(cand)) and k in by_path:
                for nid in by_path[k]:
                    if nid != sid:
                        matches.setdefault(nid, []).append((mp, cand))
        # basename fallback if chain missed
        if not matches:
            nb = norm_base(os.path.splitext(os.path.basename(mp))[0] + '.mp4')
            for nid, npath, size, dur in by_base.get(nb, []):
                if nid != sid:
                    matches.setdefault(nid, []).append((mp, npath + ' [basename-fallback]'))

    if not matches:
        results['unmatched'].append({'id': sid, 'paths': s['_missing_paths'],
                                     'has_meta': bool(s['performers'] or s['tags'] or s['stash_ids'] or s['title'])})
    elif len(matches) == 1:
        nid, ev = next(iter(matches.items()))
        results['matched'].append({'stale_id': sid, 'new_id': int(nid), 'evidence': ev})
    else:
        results['ambiguous'].append({'id': sid, 'candidates': {k: v for k, v in matches.items()}})

ts = time.strftime('%Y%m%d_%H%M%S')
dest = os.path.join(EXPORTS, f'migration-match-{ts}.json')
json.dump(results, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print({k: len(v) for k, v in results.items()})
print('->', dest)
