"""Audit Z:\\Video root filenames against NAMING_RULES.md conventions.
Read-only: produces exports/root-naming-audit.md + .csv. No renames.
"""
import os, re, csv, json, difflib, collections

ROOT = r'Z:\Video'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_MD = os.path.join(REPO, 'exports', 'root-naming-audit.md')
OUT_CSV = os.path.join(REPO, 'exports', 'root-naming-audit.csv')

VID = {'.mp4', '.wmv', '.avi', '.mpg', '.mpeg', '.asf', '.f4v', '.flv', '.mkv'}

perf = json.load(open(r'D:/Temp/performers.json'))
PERF = set(perf['names']) | set(perf['aliases'])
PERF_L = {p.lower(): p for p in PERF}
PERF_FIRST = {}          # "firstname" -> [full names] for single-name segments
for p in PERF:
    parts = p.split()
    if len(parts) > 1:
        PERF_FIRST.setdefault(parts[0].lower(), []).append(p)
        PERF_FIRST.setdefault(parts[-1].lower(), []).append(p)

RES = re.compile(r'\((\d{3,4}p?|4k|8k)\)\s*$', re.I)
SCENE = re.compile(r'\bscene\s*\d+\b', re.I)
JUNK = re.compile(r'(torrents?\s*ru|viper.*forums|dvdrip|xvid|divx|xxx[-.\s]|\[.*?\]|sharego|pornolation|uppercut|pr0nstars|jiggly|xcite|clit|dfa)', re.I)

files = sorted(f for f in os.listdir(ROOT)
               if os.path.isfile(os.path.join(ROOT, f))
               and os.path.splitext(f)[1].lower() in VID)

def seg_check(segs, cat, fn):
    for i, s in enumerate(segs):
        ls = s.strip()
        if not ls:
            cat[fn].append(('empty-segment', 'double " - " produces empty segment'))
            continue
        # leading performer segments only (before studio/movie area)
        if i < 2 and ls not in ('UI', 'DVD', 'TS') and ' ' in ls:
            low = ls.lower()
            if low in PERF_L and ls != PERF_L[low]:
                cat[fn].append(('perf-case', '"%s" should be "%s"' % (ls, PERF_L[low])))
            elif low not in PERF_L and not SCENE.search(ls) and not RES.search(ls):
                m = difflib.get_close_matches(low, list(PERF_L.keys()), n=1, cutoff=0.87)
                if m:
                    cat[fn].append(('perf-typo?', '"%s" ~ "%s" (%.0f%%)' % (
                        ls, PERF_L[m[0]], difflib.SequenceMatcher(None, low, m[0]).ratio()*100)))

rows = []
cat = collections.defaultdict(list)
for fn in files:
    stem, ext = os.path.splitext(fn)
    flags = []
    # 1. dash spacing: letter-letter hyphens that look like missing " - "
    tight = re.findall(r'\w+-+\w+', stem)
    sus = [t for t in tight if re.match(r'[A-Za-z]{3,}-[A-Za-z]{3,}', t)]
    if sus:
        flags.append(('dash-spacing', 'tight hyphens: ' + ', '.join(sus[:4])))
    if '  ' in stem:
        flags.append(('double-space', 'double space'))
    if stem != stem.strip():
        flags.append(('edge-space', 'leading/trailing space'))
    if re.search(r'\s\.\w+$', fn):
        flags.append(('space-before-ext', 'space before extension'))
    if '_' in stem:
        flags.append(('underscores', 'underscores present'))
    # 2-4. segment-level checks
    segs = [s.strip() for s in stem.split(' - ')]
    seg_check(segs, cat, fn)
    flags += cat[fn]
    # all-caps words (len>=4, not acronyms/UI/DVD/TS/HD/POV/BBW/MILF/etc.)
    acro = {'UI','DVD','TS','HD','POV','BBW','MILF','GILF','BBC','JAV','BTS','XXX','DAP','DP','IR','ATM','ATM','PSE','GFE','FFM','MMF','BDSM','SFW','NSFW','VR','II','III','IV','VI','VII','IX','XI','XII','I'}
    caps = [w for w in re.findall(r'\b[A-Z]{4,}\b', stem) if w not in acro]
    if caps:
        flags.append(('all-caps', 'caps words: ' + ', '.join(set(caps))))
    # leading lowercase word (name-ish)
    first = segs[0]
    if re.match(r'^[a-z]', first) and len(first) > 3 and first.lower() not in {'the','a','an','ui','dvd','ts'}:
        flags.append(('lowercase-lead', 'first segment starts lowercase: "%s"' % first[:40]))
    # missing resolution suffix
    if not RES.search(stem):
        flags.append(('no-res-suffix', 'no (NNN) suffix'))
    # junk/release-group tokens
    if JUNK.search(stem):
        flags.append(('release-junk', 'release-group/watermark tokens'))
    # no segment structure at all
    if ' - ' not in stem:
        flags.append(('no-segments', 'single segment, no " - " delimiters'))
    for code, msg in flags:
        rows.append({'file': fn, 'code': code, 'detail': msg})

# write csv
with open(OUT_CSV, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=['file', 'code', 'detail'])
    w.writeheader()
    w.writerows(rows)

# summarise
bycode = collections.Counter(r['code'] for r in rows)
byfile = collections.Counter(r['file'] for r in rows)
md = ['# Z:\\Video root — filename audit', '',
      'Files scanned: %d (.mp4 + preserved originals; names are shared)' % len(files), '',
      '## Issue counts', '']
for c, n in bycode.most_common():
    md.append('- **%s**: %d files' % (c, n))
md += ['', '## Per-code details (top examples)', '']
for c, n in bycode.most_common():
    md.append('### %s (%d)' % (c, n))
    ex = [r for r in rows if r['code'] == c][:40]
    for r in ex:
        md.append('- `%s` — %s' % (r['file'], r['detail']))
    if n > 40:
        md.append('- … %d more in CSV' % (n - 40))
    md.append('')
open(OUT_MD, 'w', encoding='utf-8').write('\n'.join(md))
print('files:', len(files))
print(dict(bycode))
print('wrote', OUT_MD, 'and', OUT_CSV)
