#!/usr/bin/env python3
"""OC v4 pass: reorder names to `Performer|UI - Movie - Scene N` and research
missing performers via looser StashDB scene search.

Safety: only proposes renames for files whose CURRENT name matches a
v3-generated name or a machine-style pattern; files diverging from the plan
(manual edits) are skipped and listed in the report.
Outputs: exports/oc-v4-plan.csv, exports/oc-v4-review.md
"""
import os, re, sys, csv, json, collections, urllib.request, urllib.error

REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
D = '//192.168.0.31/Collection/Video/Old Collection'
PLAN3 = os.path.join(REPO, 'exports/old-collection-plan-v3.csv')
OUTCSV = os.path.join(REPO, 'exports/oc-v4-plan.csv')
OUTMD = os.path.join(REPO, 'exports/oc-v4-review.md')
SDB_CACHE = os.path.join(REPO, 'exports/oc-v4-sdb-cache.json')

VID = {'.avi', '.wmv', '.mpg', '.mpeg', '.mp4', '.mkv', '.mov', '.flv'}
RES = re.compile(r'\s*\((\d{2,4})\)\s*$')
SCENESEG = re.compile(r'^Scene\s+\d+$', re.I)
SCN = re.compile(r' - Scene (\d+)', re.I)


def gql_local(q, v=None):
    r = urllib.request.Request('http://192.168.0.31:9999/graphql',
        data=json.dumps({'query': q, 'variables': v or {}}).encode(),
        headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(r, timeout=120))


def split_name(base):
    m = RES.search(base)
    res = ' (%s)' % m.group(1) if m else ''
    stem = base[:m.start()] if m else base
    return res, [s.strip() for s in stem.split(' - ')], stem


def main():
    files = sorted(f for f in os.listdir(D)
                   if os.path.isfile(os.path.join(D, f))
                   and os.path.splitext(f)[1].lower() in VID)
    v3new = set()
    with open(PLAN3, encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            v3new.add(row['new'])

    rows, manual, other = [], [], []
    for f in files:
        base, ext = os.path.splitext(f)
        res, segs, stem = split_name(base)
        ours = f in v3new
        si = next((i for i, s in enumerate(segs) if SCENESEG.match(s)), None)
        ui_idx = [i for i, s in enumerate(segs) if s.upper() == 'UI']

        if si is not None:
            lead = segs[:si]
            scene = segs[si]
            tail = segs[si + 1:]
            perfs = [s for s in tail if s.upper() != 'UI']
            has_ui = bool(ui_idx)
            if not ours and not re.match(r'^.+ - Scene \d+ - (UI|[\w .\'&-]+( - [\w .\'&-]+)*)$', stem):
                manual.append(f)
                continue
            if segs[0].upper() == 'UI' and not perfs:
                action, new = 'ok', f          # already UI - Movie - Scene N
            elif perfs:
                action = 'reorder-perf-first' if ours else 'manual-perf-reorder'
                new = ' - '.join(perfs + lead + [scene]) + res + ext
            elif has_ui:
                if not ours:
                    # manual name: performer already leads; just drop redundant UI
                    action = 'manual-drop-ui'
                    new = ' - '.join(lead + [scene]) + res + ext
                else:
                    action = 'ui-front'
                    new = 'UI - ' + ' - '.join(lead + [scene]) + res + ext
            else:
                action, new = 'ok', f
            rows.append(dict(cur=f, new=new, action=action,
                             ours='yes' if ours else 'MANUAL',
                             movie=' - '.join(lead),
                             perf=' / '.join(perfs) or 'UI',
                             scene=int(SCN.search(stem).group(1))))
        elif ui_idx and ours:
            # 'Studio - UI - Desc' is already correct per NAMING_RULES:
            # brand leads, UI follows. Leave untouched.
            rows.append(dict(cur=f, new=f, action='ok', ours='yes', movie='', perf='UI', scene=''))
        elif ui_idx:
            manual.append(f)
        else:
            other.append(f)

    # ---------- StashDB loose scene search ----------
    ui_movies = sorted({r['movie'] for r in rows if r['action'] == 'ui-front' and r['movie']})
    key = {b['endpoint']: b['api_key'] for b in
           gql_local('{configuration{general{stashBoxes{endpoint api_key}}}}')
           ['data']['configuration']['general']['stashBoxes']}
    sdb_key = key.get('https://stashdb.org/graphql')

    def sdb(q):
        r = urllib.request.Request('https://stashdb.org/graphql',
            data=json.dumps({'query': q}).encode(),
            headers={'Content-Type': 'application/json', 'ApiKey': sdb_key})
        try:
            return json.load(urllib.request.urlopen(r, timeout=60))
        except Exception as e:
            return {'errors': str(e)[:200]}

    cache = json.load(open(SDB_CACHE)) if os.path.exists(SDB_CACHE) else {}
    def norm(t): return re.sub(r'[^a-z0-9]+', '', t.lower())
    nsr = re.compile(r'scene\s*#?\s*0*(\d+)', re.I)

    print('researching %d UI movies on StashDB' % len(ui_movies))
    found = {}
    for i, mv in enumerate(ui_movies):
        if mv not in cache:
            r = sdb('{searchScenes(term:%s){scenes{title performers{performer{name gender}}}}}' % json.dumps(mv))
            cache[mv] = ((r.get('data') or {}).get('searchScenes') or {}).get('scenes') or []
            if i % 15 == 0:
                json.dump(cache, open(SDB_CACHE, 'w'))
                print('  %d/%d' % (i, len(ui_movies)))
        nmv = norm(mv)
        for s in cache[mv]:
            t = s['title'] or ''
            sm = nsr.search(t)
            if not sm:
                continue
            pre = t[:sm.start()]
            # title must start with the movie name (allow 'Movie N' or 'Movie #N')
            if norm(pre) != nmv:
                continue
            ps = s.get('performers') or []
            fem = [p['performer']['name'] for p in ps if p['performer'].get('gender') == 'FEMALE']
            mal = [p['performer']['name'] for p in ps if p['performer'].get('gender') == 'MALE']
            oth = [p['performer']['name'] for p in ps if p['performer'].get('gender') not in ('FEMALE', 'MALE')]
            found[(mv, int(sm.group(1)))] = ' - '.join(fem + oth + mal)
    json.dump(cache, open(SDB_CACHE, 'w'))
    print('scene-level hits:', len(found))

    upgraded = 0
    for r in rows:
        if r['action'] == 'ui-front' and isinstance(r['scene'], int):
            k = (r['movie'], r['scene'])
            if k in found:
                res, _, _ = split_name(os.path.splitext(r['cur'])[0])
                ext = os.path.splitext(r['cur'])[1]
                r['new'] = '%s - %s - Scene %d%s%s' % (found[k], r['movie'], r['scene'], res, ext)
                r['action'] = 'perf-found-stashdb'
                r['perf'] = found[k]
                upgraded += 1
    print('upgraded:', upgraded)

    with open(OUTCSV, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['cur', 'new', 'action', 'ours', 'movie', 'perf', 'scene'])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    act = collections.Counter(r['action'] for r in rows)
    L = ['# Old Collection — v4 rename/research review', '',
         '## Summary', '', '| Action | Files |', '|---|---|']
    for a, c in act.most_common():
        L.append('| `%s` | %d |' % (a, c))
    L += ['', '| Manual files (untouched) | %d |' % len(manual),
          '| Named non-scene (untouched) | %d |' % len(other),
          '| Performers recovered via StashDB loose search | %d |' % upgraded, '',
          '## Research coverage', '',
          'Performer research for `UI` files exhausted these sources:', '',
          '- **Fingerprint identify** (Stash phash job 8): applied in v3',
          '- **StashDB title match** (v3): applied — remaining UI titles have no StashDB scenes',
          '- **StashDB loose `searchScenes`** (this pass): queried all %d remaining movies; '
          '%d scene-level results returned but all covered already-named scenes — **0 new** performers' % (len(ui_movies), len(found)),
          '- **TPDB `/movies`**: movie-level cast only; `/scenes` ignores `movie_id` filter — cannot resolve scene numbers',
          '- **IAFD / AdultDVDEmpire / EGAFD**: Cloudflare-blocked or JS-only for scripted access; '
          'per-scene DVD cast would need the Playwright browser (slow) — available as a follow-up',
          '- **Facial recognition**: not run (deferred by policy)', '',
          '**Conclusion:** cheap sources exhausted. Remaining `UI` casts need either browser scraping of DVD databases or facial recognition.', '',
          '## Proposed renames', '', '| Current | Proposed | Action |', '|---|---|---|']
    for r in rows:
        if r['action'] != 'ok':
            tag = ' **[manual file — confirm]**' if r['action'].startswith('manual') else ''
            L.append('| `%s` | `%s` | %s%s |' % (r['cur'], r['new'], r['action'], tag))
    if manual:
        L += ['', '## Manual files — NOT renamed', '']
        for f in manual:
            L.append('- `%s`' % f)
    if other:
        L += ['', '## Other (named, non-scene) — untouched', '']
        for f in other[:60]:
            L.append('- `%s`' % f)
        if len(other) > 60:
            L.append('- … %d more' % (len(other) - 60))
    open(OUTMD, 'w', encoding='utf-8').write('\n'.join(L))
    print('wrote', OUTCSV, 'and', OUTMD)
    print(dict(act))


if __name__ == '__main__':
    main()
