"""Apply safe mechanical filename fixes on Z:\\Video root.
- collapse double spaces, strip edge spaces, drop empty ' - ' segments
- canonical performer case from audit CSV (perf-case rows)
- fix mangled leading names (lowercase-lead rows with known names)
Renames file + same-stem siblings. Collision-checked. Logged.
"""
import csv, os, json, re, sys, collections

ROOT = r'Z:\Video'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'exports', 'root-naming-audit.csv')
LOG = os.path.join(REPO, 'exports', 'rename-safe-fixes-log.json')
DRY = '--dry' in sys.argv

SAFE = {'double-space', 'edge-space', 'space-before-ext', 'empty-segment', 'perf-case'}
LEAD_FIX = {  # lowercase-lead manual map (junk-site files deliberately absent)
    'aitlin Bell': 'Caitlin Bell',
    'ava Devine': 'Ava Devine',
    'ictoria Lobov': 'Victoria Lobov',
    'va Angelina': 'Eva Angelina',
    'russian': 'Russian',
    'teen': 'Teen',
}

audit = list(csv.DictReader(open(CSV, encoding='utf-8')))
todo = collections.defaultdict(lambda: {'codes': set(), 'case': []})
for r in audit:
    if r['code'] in SAFE:
        todo[r['file']]['codes'].add(r['code'])
        if r['code'] == 'perf-case':
            m = re.match(r'"([^"]+)" should be "([^"]+)"', r['detail'])
            if m:
                todo[r['file']]['case'].append((m.group(1), m.group(2)))
    elif r['code'] == 'lowercase-lead':
        m = re.search(r'first segment starts lowercase: "([^"]+)"', r['detail'])
        if m and m.group(1) in LEAD_FIX:
            todo[r['file']]['case'].append((m.group(1), LEAD_FIX[m.group(1)]))
            todo[r['file']]['codes'].add('lowercase-lead')


def transform(stem, info):
    s = stem.strip()
    s = re.sub(r' {2,}', ' ', s)
    segs = [x for x in (t.strip() for t in s.split(' - ')) if x]
    s = ' - '.join(segs)
    for found, canon in info['case']:
        s = s.replace(found, canon, 1)
    return s


DIR = {f: True for f in os.listdir(ROOT)}
DIR_CF = {f.casefold() for f in DIR}   # NTFS/SMB is case-insensitive
STEMS = collections.defaultdict(list)
for f in DIR:
    STEMS[os.path.splitext(f)[0]].append(f)

log = []
renamed = skipped = 0
for fn, info in sorted(todo.items()):
    if fn not in DIR:
        log.append({'file': fn, 'result': 'missing'})
        skipped += 1
        continue
    stem, _ = os.path.splitext(fn)
    new = transform(stem, info)
    if new == stem:
        continue
    sibs = [s for s in STEMS.get(stem, [])]
    own = {t.casefold() for t in sibs}   # names being moved free themselves
    moved = []
    for s in sibs:
        d = new + os.path.splitext(s)[1]
        if d.casefold() in DIR_CF and d.casefold() not in own:
            moved = None
            log.append({'file': s, 'result': 'COLLISION', 'dst': d})
            break
        moved.append((s, d))
    if moved is None:
        skipped += 1
        continue
    for s, d in moved:
        if not DRY:
            try:
                os.rename(os.path.join(ROOT, s), os.path.join(ROOT, d))
            except OSError as e:
                log.append({'file': s, 'result': 'ERROR', 'err': str(e)[:120], 'dst': d})
                skipped += 1
                continue
        DIR.pop(s, None)
        DIR[d] = True
        DIR_CF.discard(s.casefold())
        DIR_CF.add(d.casefold())
        log.append({'file': s, 'result': 'renamed', 'dst': d,
                    'codes': sorted(info['codes'])})
        renamed += 1

json.dump(log, open(LOG, 'w', encoding='utf-8'), indent=1)
print('flagged files: %d | renamed entries: %d | skipped: %d' % (len(todo), renamed, skipped))
for l in log:
    if l['result'] != 'renamed':
        print(' ', l['result'], l['file'][:80])
