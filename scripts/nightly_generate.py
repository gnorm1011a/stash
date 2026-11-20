"""Nightly Stash metadata generation (scheduled via Windows Task Scheduler, 2am).

Triggers metadataGenerate with overwrite=false so only MISSING generated
content is created. Safe to run every night - scenes already generated are
skipped server-side.

Enabled: markers, markerScreenshots, markerImagePreviews, phashes (video)

Disabled: everything else (covers, sprites, previews, imagePreviews,
  clipPreviews, transcodes, interactiveHeatmapsSpeeds, imagePhashes,
  imageThumbnails, overwrite)

Logs to %TEMP%\stash_nightly_generate.log
"""
import json, urllib.request, os, sys, datetime, time

GQL = 'http://192.168.0.31:9999/graphql'
LOG = os.path.join(os.environ.get('TEMP', '.'), 'stash_nightly_generate.log')

def q(s, v=None):
    r = urllib.request.Request(GQL, json.dumps({'query': s, 'variables': v or {}}).encode(),
                               {'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())

def log(msg):
    line = '%s %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def main():
    r = q('''mutation { metadataGenerate(input: {
        covers: false, sprites: false, previews: false, imagePreviews: false,
        clipPreviews: false,
        markers: true, markerScreenshots: true, markerImagePreviews: true,
        phashes: true, imagePhashes: false, imageThumbnails: false,
        interactiveHeatmapsSpeeds: false,
        transcodes: false, forceTranscodes: false,
        overwrite: false
    }) }''')
    jid = r['data']['metadataGenerate']
    log('generate job started: %s' % jid)
    # poll until finished, log every 5 min
    while True:
        time.sleep(300)
        j = q('{findJob(input:{id:%s}){status progress error}}' % jid)['data']['findJob']
        log('job %s %s %.1f%% %s' % (jid, j['status'], (j['progress'] or 0) * 100, j['error'] or ''))
        if j['status'] in ('FINISHED', 'CANCELLED', 'FAILED'):
            break
    log('done')

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log('ERROR: %s' % e)
        sys.exit(1)
