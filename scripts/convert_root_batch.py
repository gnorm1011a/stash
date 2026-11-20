"""Batch-convert only files sitting directly in Z:\\Video root, largest first."""
import csv, os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wmv_to_mp4 as w

ROOT = 'Z:\\Video'

ap = argparse.ArgumentParser()
ap.add_argument('--limit', type=int, default=10)
ap.add_argument('--dry', action='store_true')
ap.add_argument('--recursive', action='store_true',
                help='include subdirectories (largest-first across whole tree)')
ap.add_argument('--only', default=None,
                help='restrict to a named subdirectory under Z:\\Video (e.g. "Old Collection")')
a = ap.parse_args()

base = ROOT + '\\' + a.only if a.only else ROOT
rows = [r for r in csv.DictReader(open(w.QUEUE, encoding='utf-8'))
        if (r['path'].startswith(base + '\\') if a.recursive or a.only
            else os.path.dirname(r['path']) == ROOT)
        and r['codec'] not in w.SKIP_CODECS
        and r.get('ext', '').lower() not in w.SKIP_EXTS]
done = w.done_set()
rows = [r for r in rows if r['path'] not in done and os.path.exists(w.to_local(r['path']))]
# rows already size-sorted in queue csv
print('root pending: %d' % len(rows))
n = err = 0
for r in rows[:a.limit]:
    res = w.convert(r, a.dry)
    print('%s | %s' % (res, r['name'][:75]), flush=True)
    if res.startswith('FAIL'):
        err += 1
        if err >= 5:
            print('too many failures')
            break
    else:
        n += 1
print('done: %d converted, %d failed, %d root remain' % (n, err, len(rows) - n))
