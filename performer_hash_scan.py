import json,os,re,urllib.request,time,datetime
TMP=os.path.expandvars(r'%TEMP%')
LOG=open(TMP+r'\batchN.log','a',buffering=1)
def log(*a):print(*a,file=LOG,flush=True)
KEY=re.search(r"KEY='([^']+)'",open(TMP+r'\hash_scan.py').read()).group(1)
def _stash_key():
    r=urllib.request.urlopen(urllib.request.Request('http://192.168.0.31:9999/graphql',data=json.dumps({'query':'{ configuration{ general{ stashBoxes{ endpoint api_key } } } }'}).encode(),headers={'Content-Type':'application/json'}),timeout=30)
    for b in (json.loads(r.read())['data']['configuration']['general']['stashBoxes'] or []):
        if 'stashdb.org' in b['endpoint']:return b['api_key']
SKEY=_stash_key()
LEDGER=r'M:\Files\Repositories\Personal\Stash\hash_scan_ledger.json'
def q(query,vars=None,tries=3):
    for t in range(tries):
        try:
            r=urllib.request.urlopen(urllib.request.Request('http://192.168.0.31:9999/graphql',data=json.dumps({'query':query,'variables':vars or {}}).encode(),headers={'Content-Type':'application/json'}),timeout=120)
            d=json.loads(r.read())
            if d.get('errors'):log('GQL-ERR',str(d['errors'])[:200])
            return d.get('data') or {}
        except Exception as e:
            if t==2:log('HTTP-ERR',e);return {}
            time.sleep(3)
def tpdb(path):
    for t in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request('https://api.theporndb.net'+path,headers={'Authorization':'Bearer '+KEY,'Accept':'application/json','User-Agent':'stash-research/1.0'}),timeout=45).read())
        except Exception as e:
            if t==3:return {}
            time.sleep(4)
def sdb(query,vars=None):
    try:
        req=urllib.request.Request('https://stashdb.org/graphql',json.dumps({'query':query,'variables':vars or {}}).encode(),{'Content-Type':'application/json','ApiKey':SKEY})
        return (json.loads(urllib.request.urlopen(req,timeout=45).read()).get('data') or {})
    except Exception as e:
        log('SDB-EXC',e);return {}
ledger=json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
# fetch next 200 unscanned
newbatch=[];page=1
while len(newbatch)<400:
    d=q('query($p:Int!){ findScenes(scene_filter:{performer_count:{modifier:EQUALS,value:0}},filter:{per_page:200,page:$p,sort:"id",direction:ASC}){ scenes{ id title files{ basename duration fingerprints{ type value } } } } }',{'p':page})
    scs=d.get('findScenes',{}).get('scenes',[])
    if not scs:break
    for s in scs:
        if s['id'] not in ledger and s['files'] and s['files'][0]['fingerprints'] and len(newbatch)<400:
            newbatch.append(s)
    page+=1
log('batchN size:',len(newbatch))
json.dump(newbatch,open(os.path.join(TMP,'batchN_scenes.json'),'w'),indent=1)
def cast(scene):
    return [p.get('name') if isinstance(p,dict) else p for p in scene.get('performers') or []]
hits=cands=0
for i,s in enumerate(newbatch):
    sid=s['id']
    rec={'scanned':datetime.datetime.now().isoformat(),'file':s['files'][0]['basename'],'tpdb':None,'sdb':None,'via':[],'title':None,'date':None,'studio':None,'cast':[]}
    fps={f['type']:f['value'] for f in s['files'][0]['fingerprints']}
    if fps.get('oshash'):
        r=tpdb('/scenes?hash='+fps['oshash'])
        data=r.get('data') or []
        if data:
            sc=data[0]
            rec['tpdb']=sc.get('id');rec['via'].append('tpdb_oshash')
            rec['title']=sc.get('title');rec['date']=sc.get('date')
            rec['studio']=(sc.get('site') or {}).get('name');rec['cast']=cast(sc)
        time.sleep(0.25)
    if not rec['tpdb'] and fps.get('phash'):
        r=tpdb('/scenes?hash='+fps['phash'])
        data=r.get('data') or []
        if data:
            sc=data[0]
            rec['phash_candidate']=sc.get('id');rec['phash_title']=sc.get('title')
            rec['phash_cast']=cast(sc);rec['phash_studio']=(sc.get('site') or {}).get('name');rec['phash_date']=sc.get('date')
        time.sleep(0.25)
    vals=[v for v in fps.values() if v]
    if vals:
        d=sdb('query($v:[String!]!){ queryScenes(input:{fingerprints:{value:$v,modifier:INCLUDES},per_page:25}){ scenes{ id title date code studio{ name } performers{ performer{ name } } urls{ url } } } }',{'v':vals})
        qq=d.get('queryScenes') or {}
        if qq.get('scenes'):
            sc=qq['scenes'][0]
            rec['sdb']=sc.get('id');rec['via'].append('sdb_fp')
            if not rec['title']:
                rec['title']=sc.get('title');rec['date']=sc.get('date');rec['studio']=(sc.get('studio') or {}).get('name')
                rec['cast']=[(p.get('performer') or {}).get('name') for p in sc.get('performers') or []]
    ledger[sid]=rec
    if rec['tpdb'] or rec['sdb']:hits+=1
    if rec.get('phash_candidate'):cands+=1
    if i%10==0:log('scan',i,'hits',hits,'phash-cands',cands);json.dump(ledger,open(LEDGER,'w'),indent=1)
json.dump(ledger,open(LEDGER,'w'),indent=1)
log('scan done. hits:',hits,'phash candidates:',cands)
# apply only oshash/sdb hits
bids={s['id'] for s in newbatch}
newhits={k:v for k,v in ledger.items() if k in bids and (v['tpdb'] or v['sdb'])}
idx={};page=1
while True:
    d=q('query($p:Int!){ findPerformers(filter:{per_page:100,page:$p}){ performers{ id name alias_list } } }',{'p':page})
    for pr in d.get('findPerformers',{}).get('performers',[]):
        idx[pr['name'].lower()]=pr['id']
        for a in pr.get('alias_list') or []:idx.setdefault(a.lower(),pr['id'])
    if len(d.get('findPerformers',{}).get('performers',[]))<100:break
    page+=1
def studio_id(name):
    d=q('query($n:String!){ findStudios(studio_filter:{name:{value:$n,modifier:EQUALS}}){ studios{ id } } }',{'n':name})
    st=d.get('findStudios',{}).get('studios') or []
    if st:return st[0]['id']
    d=q('mutation($n:String!){ studioCreate(input:{name:$n}){ id } }',{'n':name})
    return d.get('studioCreate',{}).get('id')
q('mutation($m:BoolMap!){ setPluginsEnabled(enabledMap:$m) }',{'m':{'renamefile':False,'TPDBMarkers':False,'setPerformersFromTags':False,'stashdb-performer-gallery':False}})
done=fail=0;unmatched=set()
for sid,rec in newhits.items():
    s=q('query($i:ID!){ findScene(id:$i){ id title date urls stash_ids{ endpoint stash_id } studio{ id } performers{ id } } }',{'i':sid})
    sc=s.get('findScene') or {}
    if not sc:fail+=1;continue
    upd={'id':sid}
    if not sc.get('title') and rec.get('title'):upd['title']=rec['title']
    if not sc.get('date') and rec.get('date'):upd['date']=rec['date']
    if not sc.get('studio') and rec.get('studio') and not rec['studio'].startswith('FansDB'):
        st=studio_id(rec['studio'])
        if st:upd['studio_id']=st
    perfs=[p['id'] for p in sc.get('performers',[])]
    addp=[]
    for n in rec.get('cast') or []:
        pid=idx.get((n or '').lower())
        if pid and pid not in perfs:addp.append(pid)
        elif not pid and n:unmatched.add(n)
    if addp:upd['performer_ids']=perfs+addp
    if len(upd)>1:
        r=q('mutation($in:SceneUpdateInput!){ sceneUpdate(input:$in){ id } }',{'in':upd})
        if r.get('sceneUpdate'):done+=1
        else:fail+=1;log('fail',sid)
    if rec.get('sdb') and not any(x['endpoint']=='https://stashdb.org/graphql' for x in sc.get('stash_ids',[])):
        q('mutation($in:SceneUpdateInput!){ sceneUpdate(input:$in){ id } }',{'in':{'id':sid,'stash_ids':(sc.get('stash_ids') or [])+[{'endpoint':'https://stashdb.org/graphql','stash_id':rec['sdb']}]}})

# --- write details notes for phash candidates ---
for sid,rec in [(k,v) for k,v in ledger.items() if k in bids and v.get('phash_candidate')]:
    s=q('query($i:ID!){ findScene(id:$i){ details } }',{'i':sid})
    old=((s.get('findScene') or {}).get('details') or '')
    if 'hash-scan' in old:continue
    note='[hash-scan] TPDB phash candidate (UNVERIFIED): "%s" | %s%s | cast: %s | tpdb:%s'%(
        rec.get('phash_title') or '?',rec.get('phash_studio') or '?',
        (' '+rec['phash_date']) if rec.get('phash_date') else '',
        ', '.join(rec.get('phash_cast') or []) or 'none listed',rec['phash_candidate'])
    q('mutation($in:SceneUpdateInput!){ sceneUpdate(input:$in){ id } }',{'in':{'id':sid,'details':(old+'\n\n'+note).strip() if old else note}})
log('phash notes written')
# --- tag applied hits with missing scene search ---
TAG='1028'
for sid in newhits:
    s=q('query($i:ID!){ findScene(id:$i){ tags{ id } } }',{'i':sid})
    cur=[t['id'] for t in (s.get('findScene') or {}).get('tags',[])]
    if TAG not in cur:
        q('mutation($in:SceneUpdateInput!){ sceneUpdate(input:$in){ id } }',{'in':{'id':sid,'tag_ids':cur+[TAG]}})
log('hits tagged')
q('mutation($m:BoolMap!){ setPluginsEnabled(enabledMap:$m) }',{'m':PLUGON if 'PLUGON' in dir() else {'renamefile':True,'TPDBMarkers':True,'setPerformersFromTags':True,'stashdb-performer-gallery':True}})

log('DONE batchN: applied',done,'fail',fail,'| unmatched cast:',', '.join(sorted(unmatched)) or 'none')
