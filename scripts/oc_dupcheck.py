import sys, json, urllib.request, re, collections, csv, os
sys.stdout.reconfigure(encoding='utf-8')
GQL = 'http://192.168.0.31:9999/graphql'
def q(s, v=None):
    r = urllib.request.Request(GQL, json.dumps({'query': s, 'variables': v or {}}).encode(),
                               {'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())
OCP = '/mnt/Nasferatu/Collection/Unfiled/Old Collection'
def norm(t):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', t.lower())).strip()

lib = collections.defaultdict(list)
cnt = q('{findScenes(filter:{per_page:0}){count}}')['data']['findScenes']['count']
for pg in range(1, cnt // 500 + 2):
    d = q('{findScenes(filter:{per_page:500,page:%d}){scenes{title files{path height}}}}' % pg)
    for s in d['data']['findScenes']['scenes']:
        m = re.match(r'^(.*?)\s*-\s*Scene\s*(\d+)', s.get('title') or '', re.I)
        if m and any(not f['path'].startswith(OCP) for f in s['files']):
            h = max((f.get('height') or 0) for f in s['files'] if not f['path'].startswith(OCP))
            lib[(norm(re.sub(r'\(\d{4}\)', '', m.group(1))), int(m.group(2)))].append((s['title'], h))

path = '//192.168.0.31/Media/Files/Repositories/Personal/Stash/exports/old-collection-plan-v2.csv'
rows = list(csv.DictReader(open(path, encoding='utf-8')))
for r in rows:
    r['dup'] = ''
dups = json.load(open('//192.168.0.31/Media/Files/Repositories/Personal/Stash/exports/_oc_dups.json'))
dupmap = {}
for p, tag, other in dups:
    rel = p.split('Old Collection/')[-1]
    dupmap[rel.replace('/', os.sep)] = tag + '|' + other
nf = collections.Counter()
for r in rows:
    r['dup'] = dupmap.get(r['file'], '')
    if r['status'] == 'local-match' and r['movie']:
        c = lib.get((norm(r['movie']), int(r['scene'])))
        if c:
            libh = max(x[1] for x in c)
            myh = int(r['height'] or 0)
            tag = 'dup-hq' if libh >= myh else 'oc-better'
            r['dup'] = '%s|lib %sp vs oc %sp: %s' % (tag, libh, myh, c[0][0][:60])
    nf[r['dup'].split('|')[0] or 'unique'] += 1
w = csv.DictWriter(open(path, 'w', newline='', encoding='utf-8'), fieldnames=list(rows[0].keys()))
w.writeheader(); w.writerows(rows)
print(dict(nf))
print('\nall dup rows:')
for r in rows:
    if r['dup']:
        print('  ', r['dup'].split('|')[0], '|', os.path.basename(r['file'])[:55], '->', r['dup'][:90])
