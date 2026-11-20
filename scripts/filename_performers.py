"""Option 3: filename -> performer matching.
Phase A: extract name candidates from zero-performer scene filenames,
match against LOCAL performers only (unique exact/alias match).
Dry-run: writes candidate report, no mutations.
"""
import json, urllib.request, re, os, sys
from collections import Counter

GQL='http://192.168.0.31:9999/graphql'
def gql(q,v=None):
    r=urllib.request.Request(GQL,data=json.dumps({'query':q,'variables':v or {}}).encode(),headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(r,timeout=120))

# ---------- collect studios to exclude ----------
studios=[]; page=1
while True:
    d=gql('{findStudios(filter:{per_page:200,page:%d}){count studios{name aliases}}}'%page)['data']['findStudios']
    for s in d['studios']:
        studios.append(s['name'])
        studios+=s.get('aliases') or []
    if len(studios)>=d['count']*2 or page>50: break
    page+=1
    if len(studios)>20000: break
studio_norm={re.sub(r'[^a-z0-9]','',s.lower()) for s in studios if s}
print('studio names:',len(studio_norm))

# ---------- zero-performer scenes ----------
scenes=[]; page=1
while True:
    d=gql('{findScenes(filter:{per_page:200,page:%d},scene_filter:{performer_count:{value:0,modifier:EQUALS}}){count scenes{id files{basename}}}}'%page)['data']['findScenes']
    scenes+=d['scenes']
    if len(scenes)>=d['count']: break
    page+=1
print('zero-performer scenes:',len(scenes))

# ---------- candidate extraction ----------
JUNK_SEG=re.compile(r'^(scene|sc|part|pt|vol|chapter|clip|ep|episode|bonus|intro|outro|trailer|full|hd|sd|hq|xxx|new release|final|uncut|dvdrip|webrip|cam|fps|remastered|extended|uncensored|remix)\b', re.I)
NUM_RE=re.compile(r'^\W*\d+\W*$')
QUAL_RE=re.compile(r'\b(240|320|360|400|480|540|576|640|720|900|1080|1440|2160|4320)[pi]?\b|\b(4k|8k|uhd|hd|sd)\b', re.I)
SCENE_NUM=re.compile(r'\bscene\s*\d+\b', re.I)

def is_junk(seg):
    s=seg.strip()
    if not s or NUM_RE.match(s): return True
    if JUNK_SEG.match(s): return True
    if QUAL_RE.search(s) and len(s)<20: return True
    if SCENE_NUM.search(s): return True
    if re.sub(r'[^a-z0-9]','',s.lower()) in studio_norm: return True
    # edition/year
    if re.match(r'^(19|20)\d\d$',s): return True
    return False

def looks_name(seg):
    """Conservative person-name heuristic."""
    s=seg.strip()
    if not s or is_junk(s): return False
    words=s.split()
    if len(words)>4: return False
    if len(s)<3: return False
    # must contain at least one letter run of 3+
    if not re.search(r'[A-Za-z]{3}',s): return False
    # reject if contains obvious title words
    if re.search(r'\b(the|and|for|with|gets|fucked|anal|sex|ass|cock|pussy|tits|blowjob|creampie|gangbang|orgy|party|in|on|of|my|her|his|a|to)\b',s,re.I) and len(words)<=3:
        return False
    return True

def extract(bn):
    stem=os.path.splitext(bn)[0]
    cands=[]
    # renamefile format: -(Name, Name)-{Studio}-[tags]
    m=re.search(r'-\(([^)]*)\)-\{',stem)
    if m:
        for n in re.split(r'[,;]',m.group(1)):
            if looks_name(n): cands.append(n.strip())
        stem=stem[:m.start()]
    # other paren groups mid-name: "Title (Name)"
    stem2=re.sub(r'\((\d{3,4}[pi]?)\)','',stem)  # strip (240) etc
    for m2 in re.finditer(r'\(([^)]{3,40})\)',stem2):
        for n in re.split(r'[,;&]',m2.group(1)):
            if looks_name(n): cands.append(n.strip())
    stem2=re.sub(r'\([^)]*\)','',stem2)
    for seg in stem2.split(' - '):
        seg=seg.strip()
        if not seg: continue
        # "A & B" or "A and B" within segment
        parts=re.split(r'\s*[&+]\s*|\s+and\s+(?=[A-Z])',seg)
        if len(parts)>1:
            for p in parts:
                if looks_name(p): cands.append(p.strip())
        elif looks_name(seg):
            cands.append(seg)
    # dedupe preserve order
    seen=set(); out=[]
    for c in cands:
        k=c.lower()
        if k not in seen: seen.add(k); out.append(c)
    return out

# ---------- extract all candidates ----------
all_cands={}   # name.lower -> name
scene_cands={} # scene_id -> [names]
for s in scenes:
    bn=s['files'][0]['basename'] if s['files'] else ''
    cs=extract(bn)
    if cs:
        scene_cands[s['id']]=cs
        for c in cs: all_cands.setdefault(c.lower(),c)
print('scenes with candidates:',len(scene_cands),'| unique name candidates:',len(all_cands))

# ---------- local performer matching ----------
# pull all performer names+aliases once, match locally
perfs=[]; page=1
while True:
    d=gql('{findPerformers(filter:{per_page:200,page:%d}){count performers{id name alias_list}}}'%page)['data']['findPerformers']
    perfs+=d['performers']
    if len(perfs)>=d['count']: break
    page+=1
name_map={}   # norm -> [performer]
def normp(s): return re.sub(r'\s+',' ',s.strip().lower())
for p in perfs:
    for alias in [p['name']]+(p['alias_list'] or []):
        k=normp(alias)
        if k: name_map.setdefault(k,[])
        if k and all(x['id']!=p['id'] for x in name_map[k]): name_map[k].append({'id':p['id'],'name':p['name']})
print('local performers:',len(perfs),'| name+alias keys:',len(name_map))

attach={}; ambiguous={}; nolocal={}
for sid,cs in scene_cands.items():
    for c in cs:
        k=normp(c)
        ms=name_map.get(k,[])
        if len(ms)==1: attach.setdefault(sid,[]).append(ms[0])
        elif len(ms)>1: ambiguous.setdefault(sid,[]).append((c,[m['name'] for m in ms]))
        else: nolocal.setdefault(sid,[]).append(c)

json.dump({'attach':attach,'ambiguous':{k:v for k,v in ambiguous.items()},'nolocal':nolocal},
          open(r'C:\Users\adam\AppData\Local\Temp\phaseA_report.json','w'),indent=1)
print(f'\nATTACH: {len(attach)} scenes get unique local matches')
print(f'AMBIGUOUS: {len(ambiguous)} scenes have >1 candidate')
print(f'NO LOCAL: {len(nolocal)} scenes -> phase B upstream lookup')
# samples
import itertools
print('\n--- attach samples ---')
for sid,ms in itertools.islice(attach.items(),15):
    print(' ',sid,[m['name'] for m in ms])
print('\n--- ambiguous samples ---')
for sid,ms in itertools.islice(ambiguous.items(),10):
    print(' ',sid,ms)
