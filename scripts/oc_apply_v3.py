import csv, os, sys, shutil, json, datetime, hashlib
sys.stdout.reconfigure(encoding='utf-8')
REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
VID = '//192.168.0.31/Collection/Video'
OC_UNFILED_N = os.path.normpath('//192.168.0.31/Collection/Unfiled/Old Collection')
LOG = open(os.path.join(REPO, 'exports', 'rename-applied-log.json'), 'a')

def log(**e):
    LOG.write(json.dumps({'ts': datetime.datetime.now().isoformat(), **e}) + '\n'); LOG.flush()

def dpath(dest, new):
    if dest == 'Video': return os.path.join(VID, new)
    if dest == 'Video/TS': return os.path.join(VID, 'TS', new)
    if dest == 'Video/Max Hardcore': return os.path.join(VID, 'Max Hardcore', new)
    if dest == 'Video/Old Collection': return os.path.join(VID, 'Old Collection', new)
    return None  # HOLD

rows = list(csv.DictReader(open(os.path.join(REPO, 'exports', 'old-collection-plan-v3.csv'), encoding='utf-8')))
moved = renamed = skipped = 0; errs = []
for r in rows:
    cur = r['cur']
    if not os.path.exists(cur):
        errs.append('missing ' + cur[-70:]); continue
    if r['dest'] == 'HOLD':
        dst = os.path.join(os.path.dirname(cur), r['new'])
    else:
        dst = dpath(r['dest'], r['new'])
    if os.path.normpath(cur) == os.path.normpath(dst):
        skipped += 1; continue
    if os.path.exists(dst):
        st, ex = os.path.splitext(r['new'])
        dst = os.path.join(os.path.dirname(dst), st + ' [alt]' + ex)
        if os.path.exists(dst):
            errs.append('collision ' + r['new'][:60]); continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.move(cur, dst)
        if os.path.dirname(os.path.normpath(cur)) == os.path.dirname(os.path.normpath(dst)):
            renamed += 1
        else:
            moved += 1
        log(src=cur, dst=dst, eid='', method='ocv3-' + r['src'])
    except OSError as e:
        errs.append('err %s %s' % (r['new'][:50], str(e)[:50]))
print('moved:', moved, 'renamed-in-place:', renamed, 'unchanged:', skipped, 'errors:', len(errs))
for e in errs[:15]: print('  ', e)
