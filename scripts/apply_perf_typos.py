"""Apply approved performer-name corrections to Z:\\Video root filenames.
Renames the flagged file AND any same-stem sibling (preserved original).
Logs to exports/rename-perf-typos-log.json. Skips collisions.
"""
import csv, os, json, re, sys, collections

ROOT = r'Z:\Video'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'exports', 'perf-typos.csv')
LOG = os.path.join(REPO, 'exports', 'rename-perf-typos-log.json')
DRY = '--dry' in sys.argv

rows = [r for r in csv.DictReader(open(CSV, encoding='utf-8'))]
fixes = collections.defaultdict(list)
for r in rows:
    fixes[r['file']].append((r['found'], r['suggested']))

log = []
renamed = skipped = 0
DIR = {f: True for f in os.listdir(ROOT)}          # one listing, reused
STEMS = collections.defaultdict(list)
for f in DIR:
    STEMS[os.path.splitext(f)[0]].append(f)
for fn, pairs in sorted(fixes.items()):
    if fn not in DIR:
        log.append({'file': fn, 'result': 'missing'})
        skipped += 1
        continue
    stem, ext = os.path.splitext(fn)
    new = stem
    for found, sugg in pairs:
        new = new.replace(found, sugg)
    if new == stem:
        log.append({'file': fn, 'result': 'nochange'})
        continue
    # rename this file + any same-stem siblings (other video exts)
    siblings = [s for s in STEMS.get(stem, []) if s != fn]
    todo = [fn] + siblings
    moved = []
    for s in todo:
        s_ext = os.path.splitext(s)[1]
        d = os.path.join(ROOT, new + s_ext)
        if os.path.basename(d) in DIR:
            log.append({'file': s, 'result': 'COLLISION', 'dst': os.path.basename(d)})
            moved = None
            break
        moved.append((s, os.path.basename(d)))
    if moved is None:
        skipped += 1
        continue
    for s, d in moved:
        if not DRY:
            os.rename(os.path.join(ROOT, s), os.path.join(ROOT, d))
        DIR.pop(s, None)
        DIR[d] = True
        STEMS.setdefault(new, []).append(d)
        log.append({'file': s, 'result': 'renamed', 'dst': d})
        renamed += 1

json.dump(log, open(LOG, 'w', encoding='utf-8'), indent=1)
print('files flagged: %d | entries renamed: %d | skipped/missing: %d'
      % (len(fixes), renamed, skipped))
print('collisions/missing:', [l['file'][:60] for l in log if l['result'] != 'renamed'][:15])
