# Old Collection matcher: parse Movie_Scene_N filenames, match against StashDB
# by title, join with local Stash scene records, emit audit CSV.
# Run: python old_collection_match.py
import os, re, sys, csv, json, time, urllib.request, collections

sys.stdout.reconfigure(encoding='utf-8')
GQL = 'http://192.168.0.31:9999/graphql'
REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
ROOT = '//192.168.0.31/Collection/Unfiled/Old Collection'
NAS_PREFIX = '/mnt/Nasferatu/Collection/Unfiled/Old Collection'
VEXT = {'.mp4', '.wmv', '.avi', '.mkv', '.mpg', '.mov', '.flv', '.asf', '.m4v', '.mpeg', '.rm'}
OUT = os.path.join(REPO, 'exports', 'old-collection-plan.csv')
CACHE = os.path.join(REPO, 'exports', 'old-collection-searchcache.json')

def q(s, v=None):
    r = urllib.request.Request(GQL, json.dumps({'query': s, 'variables': v or {}}).encode(),
                               {'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())

def sdb(query, var, key):
    req = urllib.request.Request('https://stashdb.org/graphql',
                                 json.dumps({'query': query, 'variables': var}).encode(),
                                 {'Content-Type': 'application/json', 'ApiKey': key})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def norm(t):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', t.lower()).replace('#', ' ')).strip()

SCENE_RE = re.compile(r'scene\s*(\d+)', re.I)
MOVIE_NUM_RE = re.compile(r'^(.*?)\s*#?(\d+)?$')

# ---------- 1. inventory ----------
vids = []
for dp, dn, fns in os.walk(ROOT):
    for f in fns:
        if os.path.splitext(f)[1].lower() in VEXT:
            vids.append(os.path.join(os.path.relpath(dp, ROOT), f))
print('videos:', len(vids))

PAT = re.compile(r'^(?P<movie>.+?)_Scene_?(?P<n>\d+)(?:_[\d-]+)?(?:_[a-z])?(?:\(\d+\))?\.', re.I)
parsed = []   # (relpath, movie, scene_n)
unparsed = []
for v in vids:
    m = PAT.match(os.path.basename(v))
    if m:
        movie = re.sub(r'[_+.]+', ' ', m.group('movie')).strip()
        parsed.append((v, movie, int(m.group('n'))))
    else:
        unparsed.append(v)
movies = sorted({p[1] for p in parsed})
print('pattern-matched:', len(parsed), '| distinct movies:', len(movies), '| unparsed:', len(unparsed))

# ---------- 2. local Stash records (fingerprint-identified from job 8) ----------
print('fetching local scene records...')
scene_by_file = {}
cnt = q('{findScenes(filter:{per_page:0}){count}}')['data']['findScenes']['count']
for pg in range(1, cnt // 500 + 2):
    d = q('{findScenes(filter:{per_page:500,page:%d}){scenes{title performers{name} studio{name} stash_ids{stash_id endpoint} files{basename path}}}}' % pg)
    for s in d['data']['findScenes']['scenes']:
        for f in s['files']:
            if f['path'].startswith(NAS_PREFIX):
                rel = os.path.relpath(f['path'].replace('/', os.sep), NAS_PREFIX.replace('/', os.sep))
                scene_by_file[rel] = s
print('local scene records under Old Collection:', len(scene_by_file))

# ---------- 3. StashDB title search (cached) ----------
key = {b['endpoint']: b['api_key'] for b in
       q('{configuration{general{stashBoxes{endpoint api_key}}}}')['data']['configuration']['general']['stashBoxes']
       }['https://stashdb.org/graphql']
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
todo = [m for m in movies if m not in cache]
print('stashdb searches needed:', len(todo))
SEARCH = '''query($t:String!){searchScenes(term:$t,limit:50){count scenes{
  id title date studio{name} performers{performer{name} as} }}}'''
for i, m in enumerate(todo):
    try:
        r = sdb(SEARCH, {'t': m}, key)
        sc = r.get('data', {}).get('searchScenes', {})
        cache[m] = sc.get('scenes') or []
    except Exception as e:
        cache[m] = []
        print('  search fail', m, str(e)[:80])
    if i % 25 == 0:
        json.dump(cache, open(CACHE, 'w'))
        print('  %d/%d' % (i, len(todo)))
    time.sleep(0.4)
json.dump(cache, open(CACHE, 'w'))

# ---------- 4. match ----------
def sdb_match(movie, n):
    """Return (scene_or_None, status)."""
    hits = []
    nm = norm(movie)
    for s in cache.get(movie) or []:
        t = norm(s['title'] or '')
        sm = SCENE_RE.search(t)
        if not sm:
            continue
        # movie title must appear as prefix-ish; allow '#N' variation
        tmovie = re.sub(r'\s*scene\s*\d+.*', '', t).strip()
        tmovie = re.sub(r'#', ' ', tmovie)
        tmovie = norm(tmovie)
        if norm(tmovie) != nm:
            continue
        hits.append((int(sm.group(1)), s))
    exact = [s for sn, s in hits if sn == n]
    if not hits:
        return None, 'movie-not-found' if not cache.get(movie) else 'movie-found-scene-miss'
    if len(exact) == 1:
        return exact[0], 'scene-match'
    if len(exact) > 1:
        return exact[0], 'scene-match-multi'
    return None, 'movie-found-scene-miss'

# ---------- 5. emit audit ----------
rows = []
for rel, movie, n in parsed:
    s_local = scene_by_file.get(rel)
    fp = bool(s_local and s_local.get('stash_ids'))
    s_sdb, status = sdb_match(movie, n)
    perfs = studio = ''
    if s_local and s_local.get('performers'):
        perfs = ';'.join(p['name'] for p in s_local['performers'])
    if s_local and s_local.get('studio'):
        studio = s_local['studio']['name']
    src = 'local-fingerprint' if fp else ''
    if not perfs and s_sdb:
        perfs = ';'.join(p['performer']['name'] for p in s_sdb['performers'])
        src = 'stashdb-title'
    if not studio and s_sdb and s_sdb.get('studio'):
        studio = s_sdb['studio']['name']
    rows.append(dict(file=rel, movie=movie, scene=n, status='fp' if fp else status,
                     sdb_title=(s_sdb or {}).get('title', ''), performers=perfs,
                     studio=studio, src=src))
for rel in unparsed:
    s_local = scene_by_file.get(rel)
    fp = bool(s_local and s_local.get('stash_ids'))
    perfs = ';'.join(p['name'] for p in s_local['performers']) if s_local and s_local.get('performers') else ''
    studio = s_local['studio']['name'] if s_local and s_local.get('studio') else ''
    rows.append(dict(file=rel, movie='', scene='', status='fp' if fp else 'unparsed',
                     sdb_title='', performers=perfs, studio=studio,
                     src='local-fingerprint' if fp else ''))
with open(OUT, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=['file', 'movie', 'scene', 'status', 'sdb_title',
                                       'performers', 'studio', 'src'])
    w.writeheader(); w.writerows(rows)
print('wrote', OUT, len(rows))
print(collections.Counter(r['status'] for r in rows))
