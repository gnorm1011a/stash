"""Option 3 Phase B: unmatched filename names -> upstream performer lookup.
Creates LINKED stubs only for unambiguous matches; logs ambiguity.
Applies: create performer (canonical remote name + stash_id) -> attach -> review tag.
"""
import json, urllib.request, urllib.error, re, time, threading, queue
from collections import Counter, defaultdict

GQL='http://192.168.0.31:9999/graphql'
UA='stash-perf-name-b/1.0'
def gql(q,v=None):
    r=urllib.request.Request(GQL,data=json.dumps({'query':q,'variables':v or {}}).encode(),headers={'Content-Type':'application/json'})
    try: return json.load(urllib.request.urlopen(r,timeout=90))
    except urllib.error.HTTPError as e: return {'err':e.read().decode()[:150]}

keys={b['endpoint']:b['api_key'] for b in gql('{configuration{general{stashBoxes{endpoint api_key}}}}')['data']['configuration']['general']['stashBoxes']}
SDB='https://stashdb.org/graphql'; TDB='https://theporndb.net/graphql'

def norm(s): return re.sub(r'[^a-z0-9]','',(s or '').lower())

def sdb_search(name):
    q='''query($q:String!){searchPerformer(search_term:$q,per_page:15){id name disambiguation gender aliases}}'''
    req=urllib.request.Request(SDB,json.dumps({'query':q,'variables':{'q':name}}).encode(),
        {'Content-Type':'application/json','ApiKey':keys[SDB]})
    try:
        r=json.loads(urllib.request.urlopen(req,timeout=40).read())
        return (r.get('data') or {}).get('searchPerformer') or []
    except urllib.error.HTTPError: return []
    except Exception: return []

def tpdb_search(name,tries=4):
    for i in range(tries):
        try:
            r=urllib.request.Request('https://api.theporndb.net/performers?q='+urllib.parse.quote(name),
                headers={'Authorization':'Bearer '+keys[TDB],'Accept':'application/json','User-Agent':UA})
            return json.loads(urllib.request.urlopen(r,timeout=40).read()).get('data') or []
        except urllib.error.HTTPError as e:
            if e.code in (404,400): return []
            time.sleep(3*(i+1))
        except Exception: time.sleep(2*(i+1))
    return []

def exact_matches(name,cands,get_name):
    n=norm(name)
    out=[]
    for c in cands:
        cn=get_name(c)
        if norm(cn)==n: out.append(c)
        else:
            # alias match counts too
            al=c.get('aliases') or []
            if any(norm(a)==n for a in al): out.append(c)
    return out

rep=json.load(open(r'C:\Users\adam\AppData\Local\Temp\phaseA_report.json'))
nolocal=rep['nolocal']
name_scenes=defaultdict(list)
for sid,cs in nolocal.items():
    for c in cs: name_scenes[norm(c)].append((sid,c))
names=[v[0][1] for k,v in name_scenes.items()]
print('unique names to look up:',len(names))

RT='1001'
results={}; work=queue.Queue()
for nm in names: work.put(nm)
lock=threading.Lock(); prog=[0]

def worker():
    while True:
        try: nm=work.get_nowait()
        except queue.Empty: return
        rec={'name':nm}
        try:
            sdb=exact_matches(nm,sdb_search(nm),lambda c:c.get('name'))
            tdb=exact_matches(nm,tpdb_search(nm),lambda c:c.get('name') or c.get('full_name'))
            rec['sdb']=[(c['id'],c.get('name'),c.get('disambiguation')) for c in sdb]
            rec['tpdb']=[(c['id'],c.get('name')) for c in tdb]
            # unique: exactly one candidate identity total across boxes
            total=len(sdb)+len(tdb)
            if total==1: rec['verdict']='unique'
            elif total==0: rec['verdict']='none'
            elif len(sdb)==1 and len(tdb)==1 and norm(sdb[0].get('name'))==norm(tdb[0].get('name')):
                rec['verdict']='both-same'  # same name on both boxes - likely same person, use sdb primary
            else: rec['verdict']='ambiguous'
        except Exception as e: rec['verdict']='err:'+str(e)[:80]
        with lock:
            results[norm(nm)]=rec; prog[0]+=1
            if prog[0]%200==0: print(prog[0],'/',len(names),flush=True)
        time.sleep(0.15)

for _ in range(3): threading.Thread(target=worker,daemon=True).start()
while work.qsize()>0: time.sleep(3)
time.sleep(2)
json.dump({'results':results,'name_scenes':name_scenes},
          open(r'C:\Users\adam\AppData\Local\Temp\phaseB_lookup.json','w'))
print(Counter(r['verdict'] for r in results.values()))
PYEOF
