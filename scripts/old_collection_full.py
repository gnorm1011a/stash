# Old Collection: full 4-pass matcher + plan emitter.
# Passes: local fingerprint (stash_ids), StashDB title, local library movie/scene
# index, TPDB movies (studio+cast). Junk files listed separately.
import os, re, sys, csv, json, time, urllib.request, collections

sys.stdout.reconfigure(encoding='utf-8')
GQL = 'http://192.168.0.31:9999/graphql'
REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
ROOT = '//192.168.0.31/Collection/Unfiled/Old Collection'
NAS_PREFIX = '/mnt/Nasferatu/Collection/Unfiled/Old Collection'
VEXT = {'.mp4', '.wmv', '.avi', '.mkv', '.mpg', '.mov', '.flv', '.asf', '.m4v', '.mpeg', '.rm'}
OUT = os.path.join(REPO, 'exports', 'old-collection-plan-v2.csv')
JUNK = os.path.join(REPO, 'exports', 'old-collection-junk.csv')
SDB_CACHE = os.path.join(REPO, 'exports', 'old-collection-searchcache.json')
TPDB_CACHE = os.path.join(REPO, 'exports', 'old-collection-tpdbcache.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'

def q(s, v=None):
    r = urllib.request.Request(GQL, json.dumps({'query': s, 'variables': v or {}}).encode(),
                               {'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())

# ---------- dictionaries for unparsed filename matching ----------
all_perfs = q('{findPerformers(filter:{per_page:10000}){performers{name alias_list gender}}}')['data']['findPerformers']['performers']
all_studios = q('{findStudios(filter:{per_page:5000}){studios{name aliases}}}')['data']['findStudios']['studios']
GENDER = {p['name'].strip(): p.get('gender') for p in all_perfs}

BAD_WORDS = set('''a an and are as at be but by for from get gets got has have her his i in is it its
my no not of on or our out she so the to too up we with you your big tit tits ass anal sex sexy hot
love loves loving fuck fucked fucking girl girls milf teen teens babe babes new now more most all
one two three four five first last best good great white black euro asian latina russian brazilian
compilation solo hard hardcore pov pmv xxx hd sd full part scene video videos ep episode vol no mr
mrs ms dr de del la le di van von der den dos das pleasure lit chu sofia marks rita wife friend busty
gold model dance dancer cum cumshot blowjob handjob facial creampie deep throat gape gaping
oiled oily wet wild public private behind between over under after before again once ever still
welcome goodbye hello hi hey hoi me my mine yours his hers ours theirs she he they we them us
purple bikini pink red blue green lingerie stockings nude naked strip striptease tease toy toys
dildo vibrator machine orgasm squirt squirting pee piss pissing pool shower bath beach bed couch
kitchen office school gym car taxi boat floor wall window door stairs hotel room home
house party club bar show live cam webcam snapchat onlyfans instagram tiktok twitter youtube
scene scenes disc cd cd1 cd2 dvd dvdrip xvid divx sample samples trailer trailers bts behind'''.split())

p_multi, p_single, s_all = {}, {}, {}
for p in all_perfs:
    cname = p['name'].strip()
    for n in [cname] + (p['alias_list'] or []):
        n = n.strip()
        if n and ' ' in n:
            p_multi.setdefault(n.lower(), (cname, n.lower() != cname.lower()))
    if ' ' not in cname.lower() and cname.lower() not in BAD_WORDS and len(cname) > 3:
        p_single[cname.lower()] = cname
for s in all_studios:
    for n in [s['name']] + (s['aliases'] or []):
        n = n.strip()
        if n and n.lower() not in ('pawg', 'milfy'):
            s_all.setdefault(n.lower(), s['name'])
P_RX = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, p_multi), key=len, reverse=True)) + r')\b', re.I)
S_RX = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, s_all), key=len, reverse=True)) + r')\b', re.I)

def dict_scan(text):
    """(performers, studios, remaining) from free text, conservative."""
    hits, flags = [], []
    for m in S_RX.finditer(text):
        hits.append((m.start(), s_all.get(m.group(0).lower(), m.group(0)), 'studio'))
    t2 = text
    for m in S_RX.finditer(text):
        t2 = t2.replace(m.group(0), ' ', 1)
    for m in P_RX.finditer(t2):
        val, is_alias = p_multi.get(m.group(0).lower(), (m.group(0), False))
        hits.append((m.start(), val, 'performer'))
        if is_alias: flags.append('alias:' + val)
    for m in P_RX.finditer(t2):
        t2 = t2.replace(m.group(0), ' ', 1)
    whole = p_single.get(t2.strip().lower())
    if whole:
        hits.append((0, whole, 'performer')); t2 = ' '
    hits.sort()
    perfs_, studs_ = [], []
    for _, val, kind in hits:
        if kind == 'performer':
            if val not in perfs_: perfs_.append(val)
        elif val not in studs_: studs_.append(val)
    rem = re.sub(r'\s+', ' ', re.sub(r'[;,]\s*', ' ', t2)).strip(' -')
    return perfs_, studs_, rem, flags

def sdb(query, var, key):
    req = urllib.request.Request('https://stashdb.org/graphql',
                                 json.dumps({'query': query, 'variables': var}).encode(),
                                 {'Content-Type': 'application/json', 'ApiKey': key})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def tpdb(path, key):
    r = urllib.request.Request('https://api.theporndb.net' + path,
                               headers={'User-Agent': UA, 'Accept': 'application/json',
                                        'Authorization': 'Bearer ' + key})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())

def norm(t):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', t.lower())).strip()

SCENE_RE = re.compile(r'scene\s*(\d+)', re.I)
FORBID = re.compile(r'[/\\:*?"<>|]')
def clean_frag(t):
    return re.sub(r'\s+', ' ', FORBID.sub(' ', t or '')).strip(' -')

# ---------- inventory ----------
vids, junk = [], []
for dp, dn, fns in os.walk(ROOT):
    for f in fns:
        rel = os.path.join(os.path.relpath(dp, ROOT), f)
        if os.path.splitext(f)[1].lower() in VEXT:
            vids.append(rel)
        elif not f.startswith('.'):
            junk.append(rel)
print('videos:', len(vids), 'junk:', len(junk))

PAT = re.compile(r'^(?P<movie>.+?)_Scene_?(?P<n>\d+)(?:_[\d-]+)?(?:_[a-z])?(?:\(\d+\))?\.', re.I)
def parse(rel):
    m = PAT.match(os.path.basename(rel))
    if m:
        return re.sub(r'[_+.]+', ' ', m.group('movie')).strip(), int(m.group('n'))
    return None, None

# ---------- local scenes: fingerprint ids, performers, studio, resolution ----------
scene_by_file = {}
cnt = q('{findScenes(filter:{per_page:0}){count}}')['data']['findScenes']['count']
movie_idx = collections.defaultdict(list)
for pg in range(1, cnt // 500 + 2):
    d = q('{findScenes(filter:{per_page:500,page:%d}){scenes{title performers{name gender} studio{name} stash_ids{stash_id endpoint} files{basename path width height bit_rate}}}}' % pg)
    for s in d['data']['findScenes']['scenes']:
        for f in s['files']:
            p = f['path']
            if p.startswith(NAS_PREFIX):
                rel = os.path.relpath(p.replace('/', os.sep), NAS_PREFIX.replace('/', os.sep))
                scene_by_file[rel.lstrip('./\\')] = (s, f)
                scene_by_file[rel] = (s, f)
            else:
                t = s.get('title') or ''
                m = re.match(r'^(.*?)\s*-\s*Scene\s*(\d+)', t, re.I)
                if m:
                    movie_idx[(norm(re.sub(r'\(\d{4}\)', '', m.group(1))), int(m.group(2)))].append(s)
print('OC scene records:', len(scene_by_file), '| library movie/scene index:', len(movie_idx))

# ---------- StashDB search (cached) ----------
keys = {b['endpoint']: b['api_key'] for b in
        q('{configuration{general{stashBoxes{endpoint api_key}}}}')['data']['configuration']['general']['stashBoxes']}
sdb_cache = json.load(open(SDB_CACHE)) if os.path.exists(SDB_CACHE) else {}

parsed = [(rel, *parse(rel)) for rel in vids]
movies = sorted({m for _, m, _ in parsed if m})
todo = [m for m in movies if m not in sdb_cache]
SEARCH = 'query($t:String!){searchScenes(term:$t,limit:50){scenes{title studio{name} performers{performer{name gender}}}}}'
for i, m in enumerate(todo):
    try:
        sdb_cache[m] = sdb(SEARCH, {'t': m}, keys['https://stashdb.org/graphql']).get('data', {}).get('searchScenes', {}).get('scenes') or []
    except Exception as e:
        sdb_cache[m] = []
    if i % 25 == 0:
        json.dump(sdb_cache, open(SDB_CACHE, 'w'))
    time.sleep(0.4)
json.dump(sdb_cache, open(SDB_CACHE, 'w'))
print('sdb searches done')

# ---------- TPDB movies (cached) ----------
tpdb_cache = json.load(open(TPDB_CACHE)) if os.path.exists(TPDB_CACHE) else {}
todo = [m for m in movies if m not in tpdb_cache]
import urllib.parse
for i, m in enumerate(todo):
    try:
        d = tpdb('/movies?' + urllib.parse.urlencode({'q': m, 'limit': 8}), keys['https://theporndb.net/graphql'])
        tpdb_cache[m] = d.get('data') or []
    except Exception as e:
        tpdb_cache[m] = []
        print('  tpdb fail', m, str(e)[:60])
    if i % 25 == 0:
        json.dump(tpdb_cache, open(TPDB_CACHE, 'w'))
    time.sleep(0.4)
json.dump(tpdb_cache, open(TPDB_CACHE, 'w'))
print('tpdb searches done')

# ---------- per-scene resolution ----------
def order_gender(perfs):
    fem = [p for p in perfs if (p.get('gender') or '').upper() in ('FEMALE', 'TRANSGENDER_FEMALE')]
    rest = [p for p in perfs if p not in fem]
    return fem + rest

LEAD_STUDIOS = {'hookup hotshot', 'facial abuse', 'ggg', 'german goo girls', 'first anal quest',
                'brcc', 'backroom casting couch', 'mom pov', 'mompoov', 'young throats',
                'mini skirt girlz', 'scores', 'scoreland', 'sex mex', 'jav', 'analized',
                'max hardcore'}
STUDIO_DISPLAY = {'german goo girls': 'GGG', 'backroom casting couch': 'BRCC', 'mom pov': 'MomPOV'}

def sdb_scene_match(movie, n):
    hits = []
    nm = norm(movie)
    for s in sdb_cache.get(movie) or []:
        t = norm(s['title'] or '')
        sm = SCENE_RE.search(t)
        if not sm:
            continue
        tmovie = re.sub(r'\s*scene\s*\d+.*', '', t).strip()
        if tmovie != nm:
            continue
        hits.append((int(sm.group(1)), s))
    exact = [s for sn, s in hits if sn == n]
    return (exact[0], 'scene-match' if len(exact) == 1 else 'scene-match-multi') if exact else (None, 'miss')

def tpdb_movie(movie):
    for m in tpdb_cache.get(movie) or []:
        if norm(m.get('title') or '') == norm(movie):
            return m
    return None

def reslabel(h):
    if not h: return None
    for cut, lab in ((2000, '4k'), (1000, '1080'), (700, '720'), (500, '576'), (440, '480'), (380, '432'), (330, '360')):
        if h >= cut: return lab
    return '240' if h >= 220 else '144'

def res_dest(h):
    return 'Video' if (h or 0) >= 720 else 'Video/Old Collection'

def compose(perfs, studio, desc, res, ext):
    perfs = list(dict.fromkeys(p for p in perfs if p))
    seg = []
    if studio and studio.lower() in LEAD_STUDIOS:
        seg.append(STUDIO_DISPLAY.get(studio.lower(), studio))
        seg += perfs[:4] if perfs else ['UI']
    elif perfs:
        seg += perfs[:4]
        if studio: seg.append(STUDIO_DISPLAY.get(studio.lower(), studio))
    elif studio:
        seg += [STUDIO_DISPLAY.get(studio.lower(), studio), 'UI']
    else:
        seg.append('UI')
    seg.append(desc)
    n = ' - '.join(clean_frag(s) for s in seg if s)
    if res: n += ' (%s)' % res
    return n + ext

def compose_movie(perfs, movie, n, res, ext):
    """Old-Collection movie rule: '<Movie> - Scene <N> - <Performers|UI>'."""
    perfs = list(dict.fromkeys(p for p in perfs if p))
    fem = [p for p in perfs if (GENDER.get(p) or '') != 'MALE']
    mal = [p for p in perfs if (GENDER.get(p) or '') == 'MALE']
    tail = fem + mal if perfs else ['UI']
    name = clean_frag(movie) + ' - Scene %d' % n + ' - ' + ' - '.join(clean_frag(p) for p in tail[:4])
    if res: name += ' (%s)' % res
    return name + ext

def dest_dir_for(new, h):
    if new.startswith('Max Hardcore - '): return 'Video/Max Hardcore'
    if new.startswith('TS - '): return 'Video/TS'
    return 'Video' if (h or 0) >= 720 else 'Video/Old Collection'

rows = []
stats = collections.Counter()
for rel, movie, n in parsed:
    ext = os.path.splitext(rel)[1]
    loc = scene_by_file.get(rel) or scene_by_file.get(rel.lstrip('./\\'))
    s_local, f_local = (loc if loc else (None, None))
    fp = bool(s_local and s_local.get('stash_ids'))
    h = (f_local or {}).get('height')
    res = reslabel(h)
    new = ''; src = ''; status = ''

    perfs_l, studio_l = [], ''
    if fp:
        perfs_l = [p['name'] for p in order_gender(s_local.get('performers') or [])]
        studio_l = s_local['studio']['name'] if s_local.get('studio') else ''
        if movie:
            new = compose_movie(perfs_l, movie, n, res, ext)
        else:
            desc = clean_frag(s_local.get('title') or '') or 'Scene'
            new = compose(perfs_l, studio_l, desc, res, ext)
        src = 'fingerprint'; status = 'fp'
    elif movie:
        s_sdb, st = sdb_scene_match(movie, n)
        li = movie_idx.get((norm(movie), n))
        if s_sdb:
            perfs_l = [x['name'] for x in order_gender(
                [dict(name=x['performer']['name'], gender=x['performer'].get('gender')) for x in s_sdb.get('performers') or []])]
            studio_l = s_sdb['studio']['name'] if s_sdb.get('studio') else ''
            src = 'stashdb'; status = st
        elif li:
            s = li[0]
            perfs_l = [p['name'] for p in order_gender(s.get('performers') or [])]
            studio_l = s['studio']['name'] if s.get('studio') else ''
            src = 'local-library'; status = 'local-match'
        else:
            tm = tpdb_movie(movie)
            studio_l = (tm.get('site') or {}).get('name', '') if tm else ''
            src = 'tpdb-movie' if tm else 'unmatched'; status = 'movie-only' if tm else 'no-match'
        new = compose_movie(perfs_l, movie, n, res, ext)
    else:
        # unparsed: dict-scan filename + parent dir names for real performers/studios
        stem = clean_frag(re.sub(r'[_+.]+', ' ', os.path.splitext(os.path.basename(rel))[0]))
        parts = [p for p in os.path.dirname(rel).split(os.sep) if p not in ('.', '')]
        context = ' '.join([stem] + [re.sub(r'[_+.]', ' ', p) for p in parts])
        dp, ds, rem, fl = dict_scan(context)
        perfs_l = order_gender([{'name': x, 'gender': GENDER.get(x)} for x in dp])
        perfs_l = [p['name'] for p in perfs_l]
        studio_l = ds[0] if ds else ''
        desc = rem or stem
        new = compose(perfs_l, studio_l, desc, res, ext)
        src = 'dict' if (perfs_l or studio_l) else 'unparsed'
        status = src
    dest = dest_dir_for(new, h)
    rows.append(dict(file=rel, movie=movie or '', scene=n or '', status=status, src=src,
                     new=new, dest=dest, res=res or '', height=h or '',
                     performers=';'.join(perfs_l), studio=studio_l,
                     movie_cast=len((tpdb_movie(movie) or {}).get('performers') or []) if movie else ''))
    stats[status] += 1

# collision check inside plan
seen = collections.Counter(r['new'].lower() for r in rows)
for r in rows:
    if seen[r['new'].lower()] > 1:
        st, ex = os.path.splitext(r['new'])
        tag = 'oc%x' % (abs(hash(r['file'])) % 0xFFFFFF)
        if st.endswith(')'):
            r['new'] = st[:-1] + ' [%s])' % tag + ex
        else:
            r['new'] = st + ' [%s]' % tag + ex

with open(OUT, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=['file', 'movie', 'scene', 'status', 'src', 'new', 'dest', 'res', 'height', 'performers', 'studio', 'movie_cast'])
    w.writeheader(); w.writerows(rows)
print('wrote', OUT, len(rows), dict(stats))

with open(JUNK, 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh); w.writerow(['file', 'ext', 'size'])
    for j in junk:
        p = os.path.join(ROOT, j)
        w.writerow([j, os.path.splitext(j)[1], os.path.getsize(p) if os.path.exists(p) else ''])
print('wrote', JUNK, len(junk))
