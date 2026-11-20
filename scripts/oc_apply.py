import csv, os, sys, shutil, json, datetime, hashlib
sys.stdout.reconfigure(encoding='utf-8')
REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
ROOT = '//192.168.0.31/Collection/Unfiled/Old Collection'
VID = '//192.168.0.31/Collection/Video'
OCD = os.path.join(VID, 'Old Collection')
os.makedirs(OCD, exist_ok=True)
LOG = open(os.path.join(REPO, 'exports', 'rename-applied-log.json'), 'a')

def log(**e):
    LOG.write(json.dumps({'ts': datetime.datetime.now().isoformat(), **e}) + '\n'); LOG.flush()

def h(p):
    x = hashlib.md5()
    with open(p, 'rb') as fh:
        while True:
            c = fh.read(1 << 21)
            if not c: break
            x.update(c)
    return x.hexdigest()

def dest_for(new, dest):
    if dest == 'Video':
        if new.startswith('TS - '): return os.path.join(VID, 'TS', new)
        if new.startswith('Max Hardcore - '): return os.path.join(VID, 'Max Hardcore', new)
        return os.path.join(VID, new)
    return os.path.join(OCD, new)

rows = list(csv.DictReader(open(os.path.join(REPO, 'exports', 'old-collection-plan-v2.csv'), encoding='utf-8')))
moved = skip_dup = 0; errs = []
for r in rows:
    src = os.path.join(ROOT, r['file'])
    if r['dup'].startswith('dup-hq'):
        skip_dup += 1; continue
    if not os.path.exists(src):
        errs.append('missing ' + r['file']); continue
    dst = dest_for(r['new'], r['dest'])
    if os.path.exists(dst):
        if h(src) == h(dst):
            os.remove(src); log(src=src, dst='DELETED-identical', eid='', method='oc'); moved += 1; continue
        st, ex = os.path.splitext(r['new'])
        dst = dest_for(st + ' [alt]' + ex, r['dest'])
        if os.path.exists(dst):
            errs.append('collision ' + r['new']); continue
    try:
        shutil.move(src, dst); moved += 1
        log(src=src, dst=dst, eid='', method='oc-' + r['src'])
    except OSError as e:
        errs.append('err %s %s' % (r['new'][:50], str(e)[:50]))
print('moved:', moved, 'held dup-hq:', skip_dup, 'errors:', len(errs))
for e in errs[:10]: print('  ', e)

# junk deletion
jr = list(csv.DictReader(open(os.path.join(REPO, 'exports', 'old-collection-junk.csv'), encoding='utf-8')))
dels = 0; jerr = []
for j in jr:
    p = os.path.join(ROOT, j['file'])
    try:
        if os.path.isfile(p):
            os.remove(p); dels += 1
            log(src=p, dst='DELETED-junk', eid='', method='oc-junk')
    except OSError as e:
        jerr.append(j['file'])
print('junk deleted:', dels, 'errors:', len(jerr))

# prune empty dirs (deepest first)
removed = 0
for dp, dn, fns in os.walk(ROOT, topdown=False):
    try:
        if not os.listdir(dp):
            os.rmdir(dp); removed += 1
    except OSError:
        pass
print('empty dirs removed:', removed)
left = []
for dp, dn, fns in os.walk(ROOT):
    for f in fns:
        left.append(os.path.join(os.path.relpath(dp, ROOT), f))
print('remaining files under Old Collection:', len(left))
