"""Snapshot all stale Stash scene records (files missing on disk) to exports/.
Read-only. Uses the pre-computed missing-file scene id list produced by the
migration plan review (missing_files.json), refreshed by re-checking disk.
"""
import json, os, sys, time, urllib.request

GQL = 'http://192.168.0.31:9999/graphql'
REPO = r'\\192.168.0.31\Media\Files\Repositories\Personal\Stash'
EXPORTS = os.path.join(REPO, 'exports')
MISSING_LIST = r'C:\Users\adam\AppData\Local\Temp\stashreview\missing_files.json'

# scene-file path (NAS) -> windows path
def to_win(nas_path):
    p = nas_path.replace('/mnt/Nasferatu/', '//192.168.0.31/').replace('/', '\\')
    return p

def gql(q, timeout=120):
    r = urllib.request.Request(GQL, data=json.dumps({'query': q}).encode(),
                               headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(r, timeout=timeout))

SCENE_FIELDS = '''id title code details director url urls date rating100 organized
o_counter play_count play_duration resume_time last_played_at play_history o_history
studio{id name} performers{id name} tags{id name} galleries{id title}
groups{group{id name} scene_index} movies{movie{id name} scene_index}
stash_ids{endpoint stash_id}
scene_markers{id title seconds end_seconds primary_tag{id name} tags{id name} screenshot stream preview}
files{id path basename size duration}
paths{screenshot preview sprite stream webp}
created_at updated_at'''

def fetch_batch(ids):
    parts = ' '.join(f's{i}:findScene(id:"{i}"){{{SCENE_FIELDS}}}' for i in ids)
    r = gql('{' + parts + '}')
    if 'errors' in r:
        raise RuntimeError(r['errors'])
    return [v for v in r['data'].values() if v]

def main():
    mf = json.load(open(MISSING_LIST, encoding='utf-8'))
    # missing_files.json: {scene_id: [missing paths]} per review artifacts
    if isinstance(mf, dict):
        stale_ids = sorted(int(k) for k in mf)
    else:
        stale_ids = sorted(int(s['id']) for s in mf)
    print(f'{len(stale_ids)} candidate stale scenes')

    out = []
    t = time.time()
    for i in range(0, len(stale_ids), 100):
        batch = stale_ids[i:i+100]
        scenes = fetch_batch(batch)
        for s in scenes:
            # re-verify staleness on disk right now
            missing = [f['path'] for f in s['files']
                       if not os.path.exists(to_win(f['path']))]
            present = [f['path'] for f in s['files']
                       if os.path.exists(to_win(f['path']))]
            s['_missing_paths'] = missing
            s['_present_paths'] = present
            s['_all_missing'] = not present
            out.append(s)
        print(f'{i+len(batch)}/{len(stale_ids)} fetched ({time.time()-t:.0f}s)', flush=True)

    ts = time.strftime('%Y%m%d_%H%M%S')
    dest = os.path.join(EXPORTS, f'stale-snapshot-{ts}.json')
    json.dump({'generated': ts, 'count': len(out), 'scenes': out},
              open(dest, 'w', encoding='utf-8'), ensure_ascii=False)
    n_curated = sum(1 for s in out if s['performers'] or s['tags'] or s['stash_ids']
                    or s['title'] or s['details'] or s['scene_markers']
                    or s['play_count'] or s['o_counter'] or s['groups'] or s['galleries'])
    print(f'saved {len(out)} scenes ({n_curated} metadata-bearing) -> {dest}')

if __name__ == '__main__':
    main()
