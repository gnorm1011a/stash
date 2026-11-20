"""unfiled_rename_v4 - rebuild clean filenames for Collection/Unfiled/Renamed.

Hard rules vs the v1-v3 attempts:
  - Never invent performer names. Names only come from:
      a) Stash scene performers[] (post-scan/identify)
      b) dictionary hits - canonical names, plus MULTIWORD aliases only
      c) reviewer overrides
  - Single-word names: canonical name only, never aliases, never common words,
    and flagged 'single-name' for review.
  - Alias hits (matched text != canonical spelling) are flagged 'alias-of'.
  - Parse the RAW eporner title, preserve original casing.
  - Fallback: `UI - <cleaned description>`.

Writes exports/unfiled-rename-plan-v4.csv. No renames are applied here.
"""
import csv, json, os, re, sys, urllib.request
sys.stdout.reconfigure(encoding='utf-8')

GQL = 'http://192.168.0.31:9999/graphql'
REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
RENM_DIR = '//192.168.0.31/Collection/Unfiled/Renamed'
VIDEO_DIR = '//192.168.0.31/Collection/Video'
VIDEO_MODE = '--video' in sys.argv  # process raw EPORNER files in Video root instead of Renamed
TR_MODE = '--torename' in sys.argv  # process Unfiled/To Rename batch
OUT = os.path.join(REPO, 'exports', 'video-eporner-rename-plan.csv' if VIDEO_MODE
                   else 'torename-plan.csv' if TR_MODE else 'unfiled-rename-plan-v4.csv')

def q(s, v=None):
    r = urllib.request.Request(GQL, json.dumps({'query': s, 'variables': v or {}}).encode(),
                               {'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())

# ---------- live dictionaries ----------
perfs = q('{findPerformers(filter:{per_page:10000}){performers{name alias_list gender}}}')['data']['findPerformers']['performers']
studios = q('{findStudios(filter:{per_page:5000}){studios{name aliases}}}')['data']['findStudios']['studios']
GENDER = {p['name'].strip(): p.get('gender') for p in perfs}

BAD_WORDS = set('''a an and are as at be but by for from get gets got has have her his i in is it its
my no not of on or our out she so the to too up we with you your big tit tits ass anal sex sexy hot
love loves loving fuck fucked fucking girl girls milf teen teens babe babes new now more most all
one two three four five first last best good great white black euro asian latina russian brazilian
compilation solo hard hardcore pov pmv xxx hd sd full part scene video videos ep episode vol no mr
mrs ms dr de del la le di van von der den dos das pleasure lit chu sofia marks rita wife friend busty
gold model model dance dancer cum cumshot blowjob handjob facial creampie deep throat gape gaping
oiled oily wet wild public private behind between over under after before again once ever still
welcome goodbye hello hi hey hoi me my mine yours his hers ours theirs she he they we them us
purple bikini pink red blue green lingerie stockings nude naked strip striptease tease toy toys
dildo vibrator machine orgasm squirt squirting pee piss pissing pool shower bath beach bed couch
kitchen office school gym car taxi boat pool table floor wall window door stairs hotel room home
house party club bar show live cam webcam snapchat onlyfans instagram tiktok twitter youtube'''.split())

def esc(s):
    return re.escape(s.strip())

# performer index: regex alternation -> canonical name; flags
p_multi = {}   # multiword canonical + multiword aliases
p_single = {}  # single-word canonical only
for p in perfs:
    cname = p['name'].strip()
    canon_key = cname.lower()
    for n in [cname] + (p['alias_list'] or []):
        n = n.strip()
        if not n: continue
        if ' ' in n:
            p_multi.setdefault(n.lower(), (cname, n.lower() != canon_key))
    if ' ' not in canon_key and canon_key not in BAD_WORDS and len(canon_key) > 3:
        p_single[canon_key] = cname
# studios that are not real brands for naming purposes (genre/tag words that live in the db)
STUDIO_BLOCK = {'pawg', 'milfy'}

s_all = {}
for s in studios:
    for n in [s['name']] + (s['aliases'] or []):
        n = n.strip()
        if n and n.lower() not in STUDIO_BLOCK: s_all.setdefault(n.lower(), s['name'])

P_RX = re.compile(r'\b(' + '|'.join(sorted(map(esc, p_multi), key=len, reverse=True)) + r')\b', re.I)
S_RX = re.compile(r'\b(' + '|'.join(sorted(map(esc, s_all), key=len, reverse=True)) + r')\b', re.I) if s_all else None

RE_ID = re.compile(r'\[([A-Za-z0-9]{11,12})\]')
RE_RES = re.compile(r'\((\d{3,4})\)\s*$')
RE_RES_ANY = re.compile(r'\b(2160p?|1440p?|1080p?|720p?|480p?|360p?|240p?|4k|uhd|fhd|hd|sd)\b', re.I)
MARKUP_JUNK = re.compile(r'(?i)\b(web[\s.-]*dl|webrip|xxx|rarbg|k2s|keep2share|repack|internal|proper|x26[45]|hevc|avc|mp4|wmv|mkv|decensored|uncensored|censored|full|complete|final|version|remaster(ed)?|upscale[ds]?|60fps|fps|pv|pmv)\b')
DATE = re.compile(r'\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b(19|20)\d{2}\b')

def clean_title(raw):
    t = re.sub(r'^EPORNER\.COM\s*-\s*', '', raw)
    t = re.sub(r'\.\w{2,4}$', '', t)
    t = RE_ID.sub(' ', t)
    res = None
    m = RE_RES.search(t)
    if m: res, t = m.group(1), RE_RES.sub('', t)
    t = re.sub(r'\{[^{}]*\}', ' ', t)
    t = re.sub(r'[\[\(]\s*([^\]\)]*?)\s*[\]\)]', r' \1 ', t)
    t = DATE.sub(' ', t)
    t = MARKUP_JUNK.sub(' ', t)
    t = RE_RES_ANY.sub(' ', t)
    t = re.sub(r'[_+.]{1,}', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip(' -')
    return t, res

def scan(text):
    """Return (performer_names, studio_names, remaining_text, flags)."""
    flags, hits = [], []
    def eat(rx, idx, kind):
        nonlocal text
        for m in rx.finditer(text):
            val, is_alias = idx.get(m.group(0).lower(), (m.group(0), False))
            hits.append((m.start(), val, kind, is_alias))
    if S_RX: eat(S_RX, {k: (v, False) for k, v in s_all.items()}, 'studio')
    text2 = text
    for m in S_RX.finditer(text) if S_RX else []:
        text2 = text2.replace(m.group(0), ' ', 1)
    eat(P_RX, p_multi, 'performer')
    for m in P_RX.finditer(text2):
        text2 = text2.replace(m.group(0), ' ', 1)
    whole = p_single.get(text2.strip().lower())
    if whole:
        hits.append((0, whole, 'performer', False))
        text2 = ' '
    hits.sort()
    perfs_, studs_ = [], []
    for _, val, kind, is_alias in hits:
        if kind == 'performer':
            if val not in perfs_: perfs_.append(val)
            if is_alias: flags.append('alias:' + val)
        else:
            if val not in studs_: studs_.append(val)
    rem = re.sub(r'[;,]\s*', ' ', text2)
    rem = re.sub(r'\s+', ' ', rem).strip(' -')
    return perfs_, studs_, rem, flags

# Category prefixes (Mode B) - free-text ethnicity/type groupings per NAMING-CONVENTION §2
CAT_LEADS = {'brazilian': 'Brazilian', 'asian': 'Asian', 'euro': 'Euro', 'latina': 'Latina',
             'teen': 'Teen', 'black': 'Black', 'russian': 'Russian', 'ts': 'TS', 'trans': 'TS',
             'transgender': 'TS', 'compilation': 'Compilation', 'amateur': 'Amateur',
             'german': 'German', 'chinese': 'Chinese', 'japanese': 'Asian'}

# Studio/series brands that lead the filename even with known performers (Mode C)
STUDIO_LEADS = {'facial abuse', 'hookup hotshot', 'ggg', 'german goo girls', 'first anal quest',
                'mini skirt girlz', 'mom pov', 'mompov', 'brcc', 'backroom casting couch',
                'young throats', 'scores', 'score', 'exploited college girls', 'ecg',
                'sex mex', 'jav'}

# preferred display for lead studios (canonical name -> filename form)
LEAD_DISPLAY = {'german goo girls': 'GGG', 'backroom casting couch': 'BRCC',
                'exploited college girls': 'ECG', 'mom pov': 'MomPOV', 'mompov': 'MomPOV'}

def order_performers(names):
    """Females (and non-male) first, males last, each group in array order."""
    return [n for n in names if GENDER.get(n) != 'MALE'] + [n for n in names if GENDER.get(n) == 'MALE']

MAX_STEM = 200  # keep total path under Windows' 260-char limit

def compose(perfs_, stud, desc, res, ext, category=None):
    """Per NAMING-CONVENTION: [Category] - (Females - Males | LeadStudio) - Studio - Desc (res)
    Unknown performer always renders 'UI' - after studio when present, else first."""
    perfs_ = list(dict.fromkeys(perfs_))
    # filename-length cap: at most 5 performers in the name (full cast stays in Stash);
    # then drop from the end, then truncate description
    if len(perfs_) > 5:
        perfs_ = perfs_[:5]
    while len(perfs_) > 1 and len(' - '.join(perfs_ + ([stud] if stud else []) + ([desc] if desc else []))) > 120:
        perfs_ = perfs_[:-1]
    parts = []
    if stud and stud.lower() in STUDIO_LEADS:
        parts = [LEAD_DISPLAY.get(stud.lower(), stud)] + (order_performers(perfs_) or ['UI'])
    else:
        if category: parts.append(category)
        if perfs_:
            parts += order_performers(perfs_)
            if stud: parts.append(stud)
        elif stud:
            parts += [stud, 'UI']
        else:
            parts += ['UI']
    if desc: parts.append(desc)
    parts = [p.strip(' -') for p in parts if p and p.strip(' -')]
    if not parts: parts = ['UI', 'Scene']
    name = ' - '.join(parts)
    if len(name) > MAX_STEM and desc:
        keep = MAX_STEM - (len(name) - len(desc))
        if keep > 20:
            name = ' - '.join(parts[:-1] + [desc[:keep].rstrip(' -')])
        else:
            name = name[:MAX_STEM].rstrip(' -')
    if res: name += ' (%s)' % res
    return name + ext

# ---------- data ----------
base = os.path.join(REPO, 'exports')
plan = {r['EpornerID']: r for r in csv.DictReader(open(base + '/unfiled-rename-plan-v3-final.csv', encoding='utf-8-sig'))}
overrides = {r['eporner_id']: r['corrected_filename'] for r in
             csv.DictReader(open(base + '/rename-corrections.csv', encoding='utf-8-sig')) if r.get('corrected_filename')}
# v4 reviewer decisions take precedence over the old corrections file
decisions = {}
try:
    decisions = {r['eporner_id']: r['corrected_filename'] for r in
                 csv.DictReader(open(base + '/unfiled-rename-v4-decisions.csv', encoding='utf-8-sig'))
                 if r.get('corrected_filename')}
except FileNotFoundError:
    pass
review_notes = {r['eporner_id']: r['review_notes'] for r in
                csv.DictReader(open(base + '/rename-issues-comprehensive.csv', encoding='utf-8-sig')) if r.get('review_notes')}

scene_rows = {}
try:
    scop = 'Video/EPORNER' if VIDEO_MODE else 'Unfiled'
    cnt = q('{findScenes(scene_filter:{path:{value:"%s",modifier:INCLUDES}} filter:{per_page:0}){count}}' % scop)['data']['findScenes']['count']
    for pg in range(1, cnt // 500 + 2):
        sc = q('{findScenes(scene_filter:{path:{value:"%s",modifier:INCLUDES}} filter:{per_page:500,page:%d}){scenes{title performers{name gender} studio{name} tags{name} files{basename}}}}' % (scop, pg))
        for s in sc['data']['findScenes']['scenes']:
            for f in s['files']:
                scene_rows[f['basename']] = s
except Exception as e:
    print('scene lookup skipped:', e)

out = []
src_dir = ('//192.168.0.31/Collection/Unfiled/To Rename' if TR_MODE
           else VIDEO_DIR if VIDEO_MODE else RENM_DIR)
for fn in sorted(os.listdir(src_dir)):
    if not re.search(r'\.(mp4|wmv|avi|mkv|mpg|mov|flv)$', fn, re.I): continue
    if VIDEO_MODE and not fn.startswith('EPORNER'): continue
    mid = RE_ID.search(fn); eid = mid.group(1) if mid else ''
    ext = os.path.splitext(fn)[1]
    raw = (plan.get(eid) or {}).get('OldFilename', fn)
    title, res = clean_title(raw)
    m2 = RE_RES.search(fn)
    if m2: res = res or m2.group(1)

    notes = []
    cat = None
    m3 = re.match(r'^(\w+)', fn)
    if m3 and m3.group(1).lower() in CAT_LEADS:
        cat = CAT_LEADS[m3.group(1).lower()]
    if eid in decisions:
        out.append(dict(file=fn, eid=eid, raw=raw, performers='', studio='', desc='',
                        new=decisions[eid], method='reviewer-v4', conf='High', notes='v4-review-sheet'))
        continue
    s = scene_rows.get(fn)
    if s and (s.get('performers') or s.get('studio')):
        perfs_ = [p['name'].strip() for p in s['performers']]
        stud = s['studio']['name'] if s.get('studio') else None
        tagnames = {t['name'].lower() for t in s.get('tags') or []}
        cat = next((CAT_LEADS[t] for t in CAT_LEADS if t in tagnames), cat)
        desc = re.sub(r'\s+', ' ', re.sub(r'[/\\:*?"<>|]', ' ', s.get('title') or '')).strip() or title
        method, conf = 'stash-scene', 'High'
    else:
        if eid in overrides:
            out.append(dict(file=fn, eid=eid, raw=raw, performers='', studio='', desc='',
                            new=overrides[eid], method='reviewer-override', conf='High', notes='corrections-csv'))
            continue
        perfs_, studs_, desc, fl = scan(title)
        stud = studs_[0] if studs_ else None
        method = 'dict' if (perfs_ or studs_) else 'ui'
        conf = 'Medium' if perfs_ else ('Low' if studs_ else 'None')
        notes += fl
        if eid in review_notes: notes.append('reviewed')
    # weeklywankcandidate/Weekleywankcandid files: Amateur - Voyeur - <name>, no UI
    if re.search(r'weekl?eywank', (raw + fn).lower()):
        stem = re.sub(r'\.(mp4|wmv|avi|mkv|mpg|mov|flv)$', '', re.sub(r'\s*\[[A-Za-z0-9]{11,12}\]', '', fn), flags=re.I)
        stem = re.sub(r'^UI\s*-\s*', '', stem)
        new = 'Amateur - Voyeur - %s%s' % (stem.strip(' -'), ext)
    else:
        new = compose(perfs_, stud, desc, res, ext, category=cat)
    out.append(dict(file=fn, eid=eid, raw=raw, performers=';'.join(perfs_), studio=stud or '',
                    desc=desc, new=new, method=method, conf=conf, notes=';'.join(notes)))

# collision disambiguation: identical targets get ' [eid]' before (res)
import collections
dups = collections.Counter(o['new'].lower() for o in out)
for o in out:
    if dups[o['new'].lower()] > 1 and o['eid']:
        stem, ext = os.path.splitext(o['new'])
        m = re.match(r'^(.*)\s\((\d{3,4})\)$', stem)
        o['new'] = ('%s [%s] (%s)%s' % (m.group(1), o['eid'], m.group(2), ext)) if m else ('%s [%s]%s' % (stem, o['eid'], ext))
        o['notes'] = (o['notes'] + ';collision' if o['notes'] else 'collision')

with open(OUT, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=['file','eid','raw','performers','studio','desc','new','method','conf','notes'])
    w.writeheader(); w.writerows(out)

import collections
print('wrote', OUT, len(out), 'rows')
print(collections.Counter(o['method'] for o in out))
print(collections.Counter(o['conf'] for o in out))
print('flagged alias:', sum('alias:' in o['notes'] for o in out))
print('flagged single:', sum('single-name' in o['notes'] for o in out))
