import json, urllib.request, urllib.error, base64, time, threading, queue

GQL='http://192.168.0.31:9999/graphql'
UA='stash-meta-fill/1.0'
def gql(q,v=None):
    r=urllib.request.Request(GQL,data=json.dumps({'query':q,'variables':v or {}}).encode(),headers={'Content-Type':'application/json'})
    try: return json.load(urllib.request.urlopen(r,timeout=90))
    except urllib.error.HTTPError as e: return {'err':e.read().decode()[:200]}

keys={b['endpoint']:b['api_key'] for b in gql('{configuration{general{stashBoxes{endpoint api_key}}}}')['data']['configuration']['general']['stashBoxes']}
SDB='https://stashdb.org/graphql'; TDB='https://theporndb.net/graphql'

def data_uri(url):
    try:
        r=urllib.request.Request(url,headers={'User-Agent':UA})
        d=urllib.request.urlopen(r,timeout=30).read()
        if len(d)<300: return None
        mime='image/jpeg' if d[:2]==b'\xff\xd8' else 'image/png' if d[:4]==b'\x89PNG' else 'image/gif' if d[:3]==b'GIF' else 'image/webp' if d[:4]==b'RIFF' else None
        if not mime: return None
        return 'data:%s;base64,%s'%(mime,base64.b64encode(d).decode())
    except Exception: return None

def sdb_perf(sid):
    q='''query($id:ID!){findPerformer(id:$id){name disambiguation aliases gender urls{url} birthdate{date accuracy} ethnicity country eye_color hair_color height measurements{band_size waist hip cup_size} breast_type career_start_year career_end_year tattoos{location description} piercings{location description} images{url}}}'''
    req=urllib.request.Request(SDB,json.dumps({'query':q,'variables':{'id':sid}}).encode(),
        {'Content-Type':'application/json','ApiKey':keys[SDB]})
    return json.loads(urllib.request.urlopen(req,timeout=40).read()).get('data',{}).get('findPerformer')

def tpdb_perf(sid,tries=3):
    for i in range(tries):
        try:
            r=urllib.request.Request('https://api.theporndb.net/performers/'+sid,
                headers={'Authorization':'Bearer '+keys[TDB],'Accept':'application/json','User-Agent':UA})
            return json.loads(urllib.request.urlopen(r,timeout=40).read()).get('data')
        except urllib.error.HTTPError as e:
            if e.code==404: return None
            time.sleep(3*(i+1))
        except Exception: time.sleep(3*(i+1))
    return 'RATE'

def mods(lst):
    return '; '.join((x.get('location','')+': '+x['description']).strip(': ') if x.get('description') else x.get('location','') for x in (lst or [])) or None

def to_update_sdb(r):
    m=r.get('measurements') or {}
    meas='-'.join(str(m[k]) for k in ('band_size','waist','hip') if m.get(k)) or None
    if m.get('cup_size') and meas: meas+=m['cup_size']
    bd=(r.get('birthdate') or {}).get('date')
    u={}
    if r.get('name'): u['name']=r['name']
    if r.get('disambiguation'): u['disambiguation']=r['disambiguation']
    if bd and len(bd)==10: u['birthdate']=bd
    for k in ('ethnicity','country','eye_color','hair_color'):
        if r.get(k): u[k]=r[k]
    if r.get('height'): u['height_cm']=r['height']
    if meas: u['measurements']=meas
    if r.get('breast_type'): u['fake_tits']='Augmented' if r['breast_type']=='AUGMENTED' else 'Natural'
    if r.get('career_start_year'): u['career_start']=r['career_start_year']
    if r.get('career_end_year'): u['career_end']=r['career_end_year']
    if mods(r.get('tattoos')): u['tattoos']=mods(r['tattoos'])
    if mods(r.get('piercings')): u['piercings']=mods(r['piercings'])
    if r.get('aliases'): u['alias_list']=r['aliases']
    if r.get('urls'): u['urls']=[x['url'] for x in r['urls']]
    if r.get('gender'): u['gender']=r['gender']
    img=(r.get('images') or [{}])[0].get('url') if r.get('images') else None
    return u,img

def to_update_tpdb(r):
    e=r.get('extras') or {}
    u={}
    if r.get('name'): u['name']=r['name']
    if e.get('birthday'): u['birthdate']=e['birthday'][:10]
    if e.get('nationality'): u['country']=e['nationality']
    if e.get('ethnicity'): u['ethnicity']=e['ethnicity']
    if e.get('hair_colour'): u['hair_color']=e['hair_colour']
    if e.get('eye_colour'): u['eye_color']=e['eye_colour']
    if e.get('height'):
        try: u['height_cm']=int(e['height'])
        except Exception: pass
    if e.get('measurements'): u['measurements']=e['measurements']
    if e.get('fake_boobs'): u['fake_tits']='Augmented'
    if e.get('career_start_year'): u['career_start']=e['career_start_year']
    if e.get('career_end_year'): u['career_end']=e['career_end_year']
    if e.get('tattoos'): u['tattoos']=e['tattoos']
    if e.get('piercings'): u['piercings']=e['piercings']
    if r.get('aliases'): u['alias_list']=r['aliases']
    if e.get('links'): u['urls']=[l['url'] if isinstance(l,dict) else l for l in e['links']]
    if e.get('gender'): u['gender']=e['gender'].upper()
    if r.get('bio'): u['details']=r['bio']
    return u,r.get('image')

targets=json.load(open(r'C:\Users\adam\AppData\Local\Temp\perf_scrape_targets.json'))['defimg']
work=queue.Queue()
for t in targets: work.put(t)
results=[]; lock=threading.Lock(); prog=[0]

def worker():
    while True:
        try: t=work.get_nowait()
        except queue.Empty: return
        pid,name=t['id'],t['name']
        row=t['sids'][0]
        rec={'id':pid,'name':name}
        try:
            if row['endpoint']==SDB:
                r=sdb_perf(row['stash_id']); upd,img=to_update_sdb(r) if r else ({},None)
            else:
                r=tpdb_perf(row['stash_id'])
                if r=='RATE': rec['status']='rate-limited'; r=None; upd,img={},None
                else: upd,img=to_update_tpdb(r) if r else ({},None)
            if not r and rec.get('status')!='rate-limited': rec['status']='remote-not-found'
            elif r:
                cur=gql('{findPerformer(id:"%s"){name birthdate details alias_list urls ethnicity gender image_path}}'%pid).get('data',{}).get('findPerformer') or {}
                inp={'id':pid}
                for k,v in upd.items():
                    if k=='alias_list':
                        merged=sorted(set((cur.get('alias_list') or []))|set(v or []))
                        if merged and merged!=sorted(cur.get('alias_list') or []): inp[k]=merged
                    elif k=='urls':
                        merged=sorted(set((cur.get('urls') or []))|set(v or []))
                        if merged and merged!=sorted(cur.get('urls') or []): inp[k]=merged
                    elif k=='name':
                        rec['remote_name']=v
                        if v.strip().lower()!=name.strip().lower():
                            clash=gql('{findPerformers(performer_filter:{name:{value:"%s",modifier:EQUALS}}){performers{id}}}'%v.replace('"','')).get('data',{}).get('findPerformers',{}).get('performers',[])
                            if not clash:
                                inp['name']=v; rec['renamed']=v
                                old=[a for a in (inp.get('alias_list') or cur.get('alias_list') or [])]
                                if name not in old: inp['alias_list']=old+[name]
                            else: rec['rename_conflict']=v
                    elif not cur.get(k) or cur.get(k) in ('',[],None): inp[k]=v
                if img and 'default=true' in (cur.get('image_path') or ''):
                    b=data_uri(img)
                    if b: inp['image']=b; rec['image']='set'
                    else: rec['image']='fetch-fail'
                if len(inp)>1:
                    out=gql('mutation($i:PerformerUpdateInput!){performerUpdate(input:$i){id}}',{'i':inp})
                    rec['status']='updated' if not out.get('errors') else 'update-err:'+str(out['errors'])[:120]
                    rec['fields']=[k for k in inp if k!='id' and k!='image']
                else: rec['status']=rec.get('status') or 'nothing-new'
        except Exception as e: rec['status']='err:'+str(e)[:120]
        with lock:
            results.append(rec); prog[0]+=1
            if prog[0]%20==0: print(prog[0],'/',len(targets),flush=True)
        time.sleep(0.15)

for _ in range(3): threading.Thread(target=worker,daemon=True).start()
while work.qsize()>0: time.sleep(2)
time.sleep(3)
json.dump(results,open(r'M:\Files\Repositories\Personal\Stash\exports\performer-metadata-fill-log.json','w'),indent=1)
from collections import Counter
print(Counter(r['status'].split(':')[0] for r in results))
print('renamed:',[(r['name'],r['renamed']) for r in results if r.get('renamed')])
print('conflicts:',[(r['name'],r['rename_conflict']) for r in results if r.get('rename_conflict')])
