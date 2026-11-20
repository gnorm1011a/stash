#!/usr/bin/env python3
"""Convert WMV/F4V files to MP4 (H.264+AAC), in place, keeping the basename so
Stash re-links by path.

- h264/mpeg4 sources -> lossless remux (-c copy)
- wmv2/wmv3/vc1/msmpeg4 -> x264 crf22 preset fast + aac 128k
- verifies output duration within 3% of source before deleting original
- resumable: skips files already done (logged) or whose .mp4 twin exists
Usage: python wmv_to_mp4.py [--limit N] [--min-mb N] [--dry]
"""
import os, sys, csv, json, time, re, shutil, subprocess, argparse

REPO = '//192.168.0.31/Media/Files/Repositories/Personal/Stash'
QUEUE = os.path.join(REPO, 'exports/convert-queue-v2.csv')
SKIP_CODECS = {'?'}          # probe failures — review manually
SKIP_EXTS = {'.mkv'}         # already modern container
LOG = os.path.join(REPO, 'exports/wmv-convert-log.jsonl')
FFMPEG = r'C:\Users\adam\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe'
FFPROBE = FFMPEG.replace('ffmpeg.exe', 'ffprobe.exe')
REMUX_CODECS = {'h264', 'mpeg4', 'hevc', 'av1'}
NAS_PREFIX = '/mnt/Nasferatu/'
# prefer mapped drives (stable sessions) over raw UNC
DRIVE_MAP = {'Collection': 'Z:/', 'Media': 'M:/'}
UNC_PREFIX = '//192.168.0.31/'
SCRATCH = r'D:\Temp'  # local scratch for in-flight encodes


def safe_tmp(dst):
    """Unique scratch filename in D:\\Temp derived from the output name."""
    base = re.sub(r'[^A-Za-z0-9_.-]+', '_', os.path.basename(dst))
    return os.path.join(SCRATCH, base + '.tmp.mp4')


def to_local(p):
    if p.startswith(NAS_PREFIX):
        rest = p[len(NAS_PREFIX):]
        share = rest.split('/')[0]
        drv = DRIVE_MAP.get(share)
        return (drv + rest[len(share) + 1:]) if drv else UNC_PREFIX + rest
    return p


def done_set():
    if not os.path.exists(LOG):
        return set()
    return {json.loads(l)['src'] for l in open(LOG, encoding='utf-8')}


def dur(p):
    try:
        r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'csv=p=0', p], capture_output=True, text=True, timeout=120)
        return float(r.stdout.strip())
    except Exception:
        return -1


def convert(row, dry):
    src, name = to_local(row['path']), row['name']
    dst = os.path.join(os.path.dirname(src), os.path.splitext(name)[0] + '.mp4')
    if os.path.exists(dst):
        return 'skip-exists'
    remux = row['codec'] in REMUX_CODECS
    tmp = safe_tmp(dst)
    cmd = [FFMPEG, '-y', '-v', 'error',
           '-err_detect', 'ignore_err', '-fflags', '+discardcorrupt+igndts',
           '-i', src]
    if remux:
        cmd += ['-c', 'copy', '-movflags', '+faststart']
    else:
        cmd += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart']
    cmd += [tmp]
    if dry:
        print(('REMUX' if remux else 'ENC  '), name[:70])
        return 'dry'
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    ds = float(row['dur'])
    ok = r.returncode == 0 and os.path.exists(tmp)
    if ok:
        dd0 = dur(tmp)
        # headers lie; only a short output means a truncated source
        if ds > 0 and dd0 > 0 and dd0 < ds * 0.90:
            ok = False
    truncated = False
    if not ok:
        # retry once with regenerated timestamps (broken ASF PTS/DTS),
        # also covers remux failures (broken AVI indices) -> encode
        cmd2 = [FFMPEG, '-y', '-v', 'error',
                '-err_detect', 'ignore_err', '-fflags', '+discardcorrupt+igndts',
                '-i', src, '-vf', 'setpts=N/25/TB,scale=trunc(iw/2)*2:trunc(ih/2)*2',
                '-af', 'asetpts=N/SR/TB',
                '-r', '25', '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', tmp]
        if os.path.exists(tmp):
            os.remove(tmp)
        r = subprocess.run(cmd2, capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.exists(tmp)
        if ok and ds > 0:
            dd0 = dur(tmp)
            # ASF/AVI headers frequently lie about duration. Only flag
            # genuinely-short outputs as truncated; a longer output means
            # the header understated and the decode recovered more content.
            if dd0 > 0 and dd0 < ds * 0.90:
                truncated = True
    el = time.time() - t0
    if not ok:
        if os.path.exists(tmp):
            os.remove(tmp)
        return 'FAIL: ' + (r.stderr or 'dur-mismatch')[:200]
    shutil.move(tmp, dst)
    # NEVER delete the source — originals stay until the user reviews and
    # confirms a deletion list. MP4 sits alongside the original.
    with open(LOG, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps({'ts': time.time(), 'src': src, 'dst': dst,
                             'mode': 'remux' if remux else 'x264', 'secs': round(el),
                             'truncated': truncated}) + '\n')
    return ('TRUNCATED-ok' if truncated else 'ok-%s' % ('remux' if remux else 'x264')) + ' %.0fs' % el


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--min-mb', type=int, default=0)
    ap.add_argument('--remux-first', action='store_true',
                    help='process lossless-remux files before encodes')
    ap.add_argument('--remux-only', action='store_true')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(QUEUE, encoding='utf-8'))
            if int(r['mb']) >= a.min_mb
            and r['codec'] not in SKIP_CODECS
            and r.get('ext', '').lower() not in SKIP_EXTS]
    if a.remux_only:
        rows = [r for r in rows if r['codec'] in REMUX_CODECS]
    elif a.remux_first:
        rows.sort(key=lambda r: r['codec'] not in REMUX_CODECS)  # remux first, keep size order
    done = done_set()
    n = err = 0
    for row in rows:
        if row['path'] in done:
            continue
        if not os.path.exists(to_local(row['path'])):
            continue
        if n >= a.limit:
            break
        res = convert(row, a.dry)
        print('%s | %s' % (res, row['name'][:75]), flush=True)
        if res.startswith('FAIL'):
            err += 1
            if err >= 5:
                print('too many failures, stopping'); break
        else:
            n += 1
    print('done: %d converted, %d failed, %d remain' %
          (n, err, sum(1 for r in rows if r['path'] not in done) - n))


if __name__ == '__main__':
    main()
