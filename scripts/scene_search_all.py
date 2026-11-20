"""Full-catalog performer research: search all zero-performer scenes against
StashDB + TPDB, score candidates on duration + title tokens + filename-performer
overlap. Outputs tiered results to exports/scene-search-all-results.json.
Hooks must be disabled (they are, session-wide)."""
import urllib.request, json, re, time, sys

GQL='http://192.168.0.31:9999/graphql'
SDB='https://stashdb.org/graphql'
TPDB='https://theporndb.net/graphql'
SDB_KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiIwMTliODM5Yi0xNDUzLTc2ODgtYTkzOS1mMDJiN2M3NDQyOTkiLCJzdWIiOiJBUElLZXkiLCJpYXQiOjE3Njc0Mzk1Mzd9.u4pMHovbbTS-KUXMglesijufjHtO4jcwnxBOJnvPVmc'
TPDB_KEY='KSn04Q3jugZAbOSdJtaAvKUSyfoErVw2t8XcvZcrf39e7574'
UA='Mozilla/5.0'

def stash(q,v=None):
    r=urllib.request.Request(GQL,data=json.dumps({'query':q,'variables':v or {}}).encode(),headers={'Content-Type':'application/json'})
    try: return json.load(urllib.request.urlopen(r,timeout=120))
    except urllib.error.HTTPError as e: return {'err':e.read().decode()[:200]}

def box(u,q,v,key):
    r=urllib.request.Request(u,data=json.dumps({'query':q,'variables':v}).encode(),
      headers={'Content-Type':'application/json','User-Agent':UA,'Authorization':'Bearer '+key})
    try: return json.load(urllib.request.urlopen(r,timeout=60))
    except urllib.error.HTTPError as e: return {'err':e.read().decode()[:200]}
    except Exception as e: return {'err':str(e)[:150]}

STOP={'a','an','the','of','in','on','at','to','and','or','is','it','ui','xxx'}
def toks(s):
    return set(t for t in re.split(r'[^a-z0-9]+',s.lower()) if t and t not in STOP)

def clean_bn(bn):
    bn=re.sub(r'\.\w{2,4}$','',bn)
    bn=re.sub(r'\s*\(\s*\d{3,4}p?\s*\)\s*$','',bn)      # (720) (1080)
    bn=re.sub(r'\s*\[[^\]]*\]','',bn)                  # [tags] anywhere
    bn=re.sub(r'\([^)]*\)','',bn)                      # (parens) anywhere
    return bn.strip(' -')

def make_query(bn):
    b=clean_bn(bn)
    segs=[s.strip() for s in b.split(' - ') if s.strip() and s.strip().lower()!='ui']
    scene_tail=re.compile(r'(?i)^(scene|part|pt|clip|ep)\b')
    if len(segs)>=3:
        body=segs[:-1] if scene_tail.match(segs[-1]) else segs
        q=' - '.join(body[1:]) or body[0]
    elif len(segs)==2:
        q=segs[0] if scene_tail.match(segs[-1]) else segs[-1]
    else:
        q=b
    return q.strip(' -')[:120]

def fname_names(bn):
    first=clean_bn(bn).split(' - ')[0]
    if ' - ' not in clean_bn(bn): return set()
    names=re.split(r',|&|\band\b',first)
    out=set()
    for n in names:
        n=n.strip()
        if re.match(r'^[A-Z][a-z]+',n): out.add(n.lower())
    return out

def scene_num(bn):
    m=re.search(r'(?i)\bscene\s*(\d+)\b',bn)
    return m.group(1) if m else None

def score(scene,cand,qtok,names,snum,dur):
    ct=toks(cand.get('title') or '')
    if not ct: return 'pool',0
    cdur=cand.get('duration') or 0
    dd=abs((dur or 0)-cdur) if cdur else 9999
    inter=len(ct & qtok); cover=inter/len(ct)
    perfs=[(p.get('performer') or {}).get('name','').lower() for p in (cand.get('performers') or [])]
    pnames=set()
    for p in perfs: pnames.update(toks(p))
    poverlap=len(names & pnames)
    cnum=None
    m=re.search(r'(?i)\bscene\s*(\d+)\b',cand.get('title') or '')
    if m: cnum=m.group(1)
    sn_match = (snum and cnum and int(snum)==int(cnum))
    if dd<=3 and cover>=0.6: return 'exact',cover
    if dd<=3 and poverlap>=1 and cover>=0.3: return 'exact',cover
    if sn_match and cover>=0.5 and dd<=60: return 'recommend',cover
    if dd<=8 and cover>=0.6: return 'recommend',cover
    return 'pool',cover

SDB_Q='''query($t:String!){ searchScenes(term:$t,per_page:10){ id title duration date
  studio{ name } performers{ performer{ name } } } }'''
TPDB_Q='''query($t:String!){ searchScene(term:$t,limit:10){ id title duration date
  studio{ name } performers{ performer{ name } } } }'''

import threading, queue

scenes=[]; page=1
while True:
    d=stash('{ findScenes(filter:{per_page:500,page:%d},scene_filter:{performer_count:{value:0,modifier:EQUALS}}){ count scenes{ id files{ basename duration } } } }'%page)
    f=d['data']['findScenes']; tot=f['count']
    scenes+=f['scenes']
    if page*500>=tot: break
    page+=1
print('zero-performer scenes:',len(scenes),flush=True)

OUT=r'M:\Files\Repositories\Personal\Stash\exports\scene-search-all-results.json'
CKPT=r'M:\Files\Repositories\Personal\Stash\exports\scene-search-all-ckpt.json'
done_ids=set()
try:
    for r in json.load(open(CKPT)): done_ids.add(r['scene_id'])
except Exception: pass
if done_ids: print('resuming, skipping',len(done_ids),flush=True)

work=queue.Queue()
for s in scenes:
    if s['id'] not in done_ids: work.put(s)
results=[]; lock=threading.Lock(); ctr=[0]; tot_todo=work.qsize()

def worker():
    while True:
        try: s=work.get_nowait()
        except queue.Empty: return
        bn=s['files'][0]['basename'] if s['files'] else ''
        dur=s['files'][0].get('duration') if s['files'] else None
        q=make_query(bn); qt=toks(clean_bn(bn)); names=fname_names(bn); snum=scene_num(bn)
        cands=[]
        for src,u,key,qq in [('stashdb',SDB,SDB_KEY,SDB_Q),('tpdb',TPDB,TPDB_KEY,TPDB_Q)]:
            d=box(u,qq,{'t':q},key)
            rows=(d.get('data') or {}).get('searchScenes') or (d.get('data') or {}).get('searchScene') or []
            for c in rows:
                t,cov=score(s,c,qt|toks(q),names,snum,dur)
                cands.append({'src':src,'id':c.get('id'),'title':c.get('title'),'duration':c.get('duration'),
                              'date':c.get('date'),'studio':(c.get('studio') or {}).get('name'),
                              'performers':[ (p.get('performer') or {}).get('name') for p in (c.get('performers') or [])],
                              'tier':t,'cover':round(cov,2)})
        rank={'exact':0,'recommend':1,'pool':2}
        cands.sort(key=lambda c:(rank[c['tier']],-c['cover']))
        best=cands[0] if cands and cands[0]['tier'] in ('exact','recommend') else None
        row={'scene_id':s['id'],'basename':bn,'duration':dur,'query':q,'best':best,'cands':cands[:5]}
        with lock:
            results.append(row); ctr[0]+=1
            if ctr[0]%200==0:
                print(f"{ctr[0]}/{tot_todo}",flush=True)
                old=[]
                try: old=json.load(open(CKPT))
                except Exception: pass
                old+=[r for r in results]; results.clear()
                json.dump(old,open(CKPT,'w'))
        time.sleep(0.05)

threads=[threading.Thread(target=worker,daemon=True) for _ in range(6)]
for t in threads: t.start()
for t in threads: t.join()

final=[]
try: final=json.load(open(CKPT))
except Exception: pass
final+=results
json.dump(final,open(OUT,'w'),indent=1)
ex=sum(1 for r in final if r['best'] and r['best']['tier']=='exact')
rec=sum(1 for r in final if r['best'] and r['best']['tier']=='recommend')
print(f'DONE exact={ex} recommend={rec} none={len(final)-ex-rec}')
