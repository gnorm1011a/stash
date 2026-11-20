# Old Collection v3: re-plan every OC file at its CURRENT location.
# Movie files:  '<Movie> - Scene <N> - <Performers|UI> (res)'
# Other files:  dict-match filename + parent dirs -> convention name.
import os, re, sys, csv, json, urllib.request, collections

sys.stdout.reconfigure(encoding='utf-8')
GQL = 'http://192.168.0.31:9999/graphql'
REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
OC_UNFILED = '//192.168.0.31/Collection/Unfiled/Old Collection'
VID = '//192.168.0.31/Collection/Video'
NAS_UNFILED = '/mnt/Nasferatu/Collection/Unfiled/Old Collection'
NAS_VID = '/mnt/Nasferatu/Collection/Video'
VEXT = {'.mp4', '.wmv', '.avi', '.mkv', '.mpg', '.mov', '.flv', '.asf', '.m4v', '.mpeg', '.rm'}
OUT = os.path.join(REPO, 'exports', 'old-collection-plan-v3.csv')
SDB_CACHE = os.path.join(REPO, 'exports', 'old-collection-searchcache.json')

def q(s, v=None):
    r = urllib.request.Request(GQL, json.dumps({'query': s, 'variables': v or {}}).encode(),
                               {'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())

def norm(t):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', t.lower())).strip()

SCENE_RE = re.compile(r'scene\s*(\d+)', re.I)
FORBID = re.compile(r'[/\\:*?"<>|]')
def clean_frag(t):
    return re.sub(r'\s+', ' ', FORBID.sub(' ', t or '')).strip(' -')

# ---------- dictionaries ----------
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
s_all.setdefault('maxhardcore', 'Max Hardcore')
s_all.setdefault('max hardcore', 'Max Hardcore')
P_RX = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, p_multi), key=len, reverse=True)) + r')\b', re.I)
S_RX = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, s_all), key=len, reverse=True)) + r')\b', re.I)

def dict_scan(text):
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

LEAD_STUDIOS = {'hookup hotshot', 'facial abuse', 'ggg', 'german goo girls', 'first anal quest',
                'brcc', 'backroom casting couch', 'mom pov', 'young throats', 'mini skirt girlz',
                'scores', 'scoreland', 'sex mex', 'jav', 'analized', 'max hardcore'}
STUDIO_DISPLAY = {'german goo girls': 'GGG', 'backroom casting couch': 'BRCC', 'mom pov': 'MomPOV'}

def order_names(perfs):
    return [p for p in perfs if (GENDER.get(p) or '') != 'MALE'] + \
           [p for p in perfs if (GENDER.get(p) or '') == 'MALE']

def compose(perfs, studio, desc, res, ext):
    perfs = list(dict.fromkeys(p for p in perfs if p))
    seg = []
    if studio and studio.lower() in LEAD_STUDIOS:
        seg.append(STUDIO_DISPLAY.get(studio.lower(), studio))
        seg += order_names(perfs[:4]) if perfs else ['UI']
    elif perfs:
        seg += order_names(perfs[:4])
        if studio: seg.append(STUDIO_DISPLAY.get(studio.lower(), studio))
    elif studio:
        seg += [STUDIO_DISPLAY.get(studio.lower(), studio), 'UI']
    else:
        seg.append('UI')
    seg.append(desc)
    n = ' - '.join(clean_frag(s) for s in seg if clean_frag(s))
    if res: n += ' (%s)' % res
    return n + ext

def compose_movie(perfs, movie, n, res, ext):
    perfs = list(dict.fromkeys(p for p in perfs if p))
    tail = order_names(perfs)[:4] if perfs else ['UI']
    name = clean_frag(movie) + ' - Scene %d' % n + ' - ' + ' - '.join(clean_frag(p) for p in tail)
    if res: name += ' (%s)' % res
    return name + ext

def reslabel(h):
    if not h: return None
    for cut, lab in ((2000, '4k'), (1000, '1080'), (700, '720'), (500, '576'), (440, '480'), (380, '432'), (330, '360')):
        if h >= cut: return lab
    return '240' if h >= 220 else '144'

def dest_for(new, h):
    if new.startswith('Max Hardcore - '): return 'Video/Max Hardcore'
    if new.startswith('TS - '): return 'Video/TS'
    return 'Video' if (h or 0) >= 720 else 'Video/Old Collection'

# ---------- current file locations ----------
# moved files: dst from log; remaining: still under Unfiled\Old Collection
cur_of = {}   # current UNC path -> original OC rel path
log_src_of = {}
for line in open(os.path.join(REPO, 'exports', 'rename-applied-log.json'), encoding='utf-8'):
    try: e = json.loads(line)
    except Exception: continue
    if (e.get('method') or '').startswith('oc') and e.get('dst') and 'DELETED' not in e['dst']:
        src = os.path.normpath(e['src'])
        rel = os.path.relpath(src, OC_UNFILED)
        cur_of[os.path.normpath(e['dst'])] = rel
        log_src_of[os.path.normpath(e['dst'])] = src

# files still under Unfiled\Old Collection (dup-hq + any strays)
for dp, dn, fns in os.walk(OC_UNFILED):
    for f in fns:
        if os.path.splitext(f)[1].lower() in VEXT:
            p = os.path.normpath(os.path.join(dp, f))
            cur_of.setdefault(p, os.path.relpath(p, OC_UNFILED))

print('files to re-plan:', len(cur_of))

# ---------- stash records by current path ----------
scene_by_path = {}
cnt = q('{findScenes(filter:{per_page:0}){count}}')['data']['findScenes']['count']
movie_idx = collections.defaultdict(list)
for pg in range(1, cnt // 500 + 2):
    d = q('{findScenes(filter:{per_page:500,page:%d}){scenes{title performers{name gender} studio{name} stash_ids{stash_id endpoint} files{basename path width height}}}}' % pg)
    for s in d['data']['findScenes']['scenes']:
        for f in s['files']:
            p = f['path']
            if p.startswith(NAS_VID):
                unc = os.path.normpath(p.replace(NAS_VID, VID))
                scene_by_path[unc] = (s, f)
                # library index for video files not under Old Collection
                if not p.startswith(NAS_VID + '/Old Collection'):
                    m = re.match(r'^(.*?)\s*-\s*Scene\s*(\d+)', s.get('title') or '', re.I)
                    if m:
                        movie_idx[(norm(re.sub(r'\(\d{4}\)', '', m.group(1))), int(m.group(2)))].append(s)
            elif p.startswith(NAS_UNFILED):
                unc = os.path.normpath(p.replace(NAS_UNFILED, OC_UNFILED))
                scene_by_path[unc] = (s, f)
            else:
                m = re.match(r'^(.*?)\s*-\s*Scene\s*(\d+)', s.get('title') or '', re.I)
                if m:
                    movie_idx[(norm(re.sub(r'\(\d{4}\)', '', m.group(1))), int(m.group(2)))].append(s)
print('scene records resolved:', len(scene_by_path))

sdb_cache = json.load(open(SDB_CACHE))
def sdb_scene_match(movie, n):
    hits = []
    nm = norm(movie)
    for s in sdb_cache.get(movie) or []:
        t = norm(s['title'] or '')
        sm = SCENE_RE.search(t)
        if not sm: continue
        tmovie = re.sub(r'\s*scene\s*\d+.*', '', t).strip()
        if tmovie != nm: continue
        hits.append((int(sm.group(1)), s))
    exact = [s for sn, s in hits if sn == n]
    return (exact[0], 'scene-match' if len(exact) == 1 else 'scene-match-multi') if exact else (None, 'miss')

PAT = re.compile(r'^(?P<movie>.+?)_Scene_?(?P<n>\d+)(?:_[\d-]+)?(?:_[a-z])?(?:\(\d+\))?\.', re.I)
# also match the OLD-plan produced names so dup-hq rel names parse too
PAT2 = re.compile(r'^(?P<movie>.+?)\s*-\s*Scene\s*(?P<n>\d+)', re.I)

rows = []
stats = collections.Counter()
for cur, orig_rel in sorted(cur_of.items()):
    ext = os.path.splitext(cur)[1]
    base = os.path.basename(orig_rel)
    movie, n = None, None
    m = PAT.match(base) or PAT2.match(base)
    if m:
        movie = re.sub(r'[_+.]+', ' ', m.group('movie')).strip(' -')
        # strip trailing ' - UI' / performer list from prev names to get bare movie title
        n = int(m.group('n'))
    loc = scene_by_path.get(cur)
    s_local, f_local = (loc if loc else (None, None))
    h = (f_local or {}).get('height')
    res = reslabel(h)
    fp = bool(s_local and s_local.get('stash_ids'))
    perfs_l, studio_l, src, status = [], '', '', ''
    if fp:
        perfs_l = order_names([p['name'] for p in s_local.get('performers') or []])
        studio_l = s_local['studio']['name'] if s_local.get('studio') else ''
        src, status = 'fingerprint', 'fp'
    elif movie:
        s_sdb, st = sdb_scene_match(movie, n)
        li = movie_idx.get((norm(movie), n))
        if s_sdb:
            perfs_l = order_names([x['performer']['name'] for x in s_sdb.get('performers') or []])
            studio_l = s_sdb['studio']['name'] if s_sdb.get('studio') else ''
            src, status = 'stashdb', st
        elif li:
            perfs_l = order_names([p['name'] for p in li[0].get('performers') or []])
            studio_l = li[0]['studio']['name'] if li[0].get('studio') else ''
            src, status = 'local-library', 'local-match'
        else:
            src, status = 'tpdb-movie', 'movie-only'
    if movie:
        new = compose_movie(perfs_l, movie, n, res, ext)
    elif fp:
        # identified but no movie/scene structure: name from scene title
        stem = clean_frag(re.sub(r'[_+.]+', ' ', os.path.splitext(os.path.basename(orig_rel))[0]))
        desc = clean_frag(s_local.get('title') or '') or stem
        new = compose(perfs_l, studio_l, desc, res, ext)
    else:
        # dict-match original filename stem + original parent dirs only
        stem = clean_frag(re.sub(r'[_+.]+', ' ', os.path.splitext(os.path.basename(orig_rel))[0]))
        parents = [re.sub(r'[_+.]', ' ', p) for p in os.path.dirname(orig_rel).split(os.sep) if p not in ('.', '')]
        # scan stem alone first; only pull parent-dir context if stem has no names
        dp, ds, rem, fl = dict_scan(stem)
        if not dp and not ds:
            dp, ds, rem, fl = dict_scan(' '.join(parents + [stem]))
        perfs_l = order_names(dp); studio_l = ds[0] if ds else ''
        desc = rem if len(rem) > 4 else (' - '.join(parents + [stem]))
        desc = re.sub(r'\bUI\b', ' ', desc); desc = re.sub(r'\s+', ' ', desc).strip(' -') or stem
        new = compose(perfs_l, studio_l, desc, res, ext)
        src = 'dict' if (perfs_l or studio_l) else 'unparsed'
        status = src
    # for dup-hq rows still in Unfiled: keep dest marker, do not move into Video dirs
    under_unfiled = cur.startswith(os.path.normpath(OC_UNFILED))
    dest = dest_for(new, h)
    rows.append(dict(cur=cur, file=orig_rel, movie=movie or '', scene=n or '', status=status,
                     src=src, new=new, dest='HOLD' if under_unfiled else dest,
                     res=res or '', height=h or '', performers=';'.join(perfs_l), studio=studio_l))
    stats[status] += 1

seen = collections.Counter(r['new'].lower() for r in rows)
for r in rows:
    if seen[r['new'].lower()] > 1:
        st, ex = os.path.splitext(r['new'])
        tag = 'oc%x' % (abs(hash(r['file'])) % 0xFFFFFF)
        r['new'] = (st[:-1] + ' [%s])' % tag + ex) if st.endswith(')') else (st + ' [%s]' % tag + ex)

with open(OUT, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=['cur', 'file', 'movie', 'scene', 'status', 'src', 'new', 'dest', 'res', 'height', 'performers', 'studio'])
    w.writeheader(); w.writerows(rows)
print('wrote', OUT, len(rows), dict(stats))
