#!/usr/bin/env python3
"""Combine split-part clips in Video\\Old Collection subfolders into MP4s.

Groups files inside each part-folder into combine units (e.g. Oil Overload
1a+1b is one video, 2a+2b another; Oil Overload 4 disc1-cd1/cd2 = DISC1, etc.),
sorts parts naturally, and concatenates them with ffmpeg's concat filter
into H.264/AAC MP4 in the Old Collection root.

Originals are kept. Sample/trailer files are skipped.
Usage: oc_combine.py [--dry] [--only NAME]
"""
import os, re, sys, json, time, subprocess, collections

D = '//192.168.0.31/Collection/Video/Old Collection'
EXP = '//192.168.0.31/Media/Files/Repositories/Personal/Stash/exports'
FFMPEG = 'ffmpeg'
RES = re.compile(r'\s*\(\d{3,4}\)\s*$')
# primitive part tokens in order of appearance: 'cd1'->(cd,1), '1a'->(num1,letter a), '01', '(3)', '-a'
TOK = re.compile(r'''(?ix)
    \b(cd|disc|disk|part|pt)\s*(\d+)\b      # cd1 disc2 part3
  | \b(sample)\b
  | \( (\d+) \)                             # (1) (3)
  | \# \s* (\d+)                            # # 3
  | [\s_\-\.] (\d+) ([a-f]) (?=\s|$)        # ' 1a' ' 5b'
  | [\s_\-\.] (\d{3,4}) (?=\s|$|\.)         # ' 001' ' 2950'
  | [\s_\-\.] (\d{1,2}) (?=\s|$|\.)         # ' 01' ' 15' ' -1'
  | [\s_\-\.] ([a-f]) (?=\s|$|\.)           # ' -a' ' -b'
''')
VID = {'.avi', '.wmv', '.mpg', '.mpeg', '.mp4', '.mkv', '.mov', '.flv'}


def tokens(name):
    """Ordered primitive token values for a filename stem."""
    b = RES.sub('', os.path.splitext(name)[0])
    out = []
    for m in TOK.finditer(b):
        g = [x for x in m.groups() if x]
        if not g:
            continue
        if g[0].lower() in ('cd', 'disc', 'disk', 'part', 'pt'):
            out.append(('disc', int(g[1])))
        elif g[0].lower() == 'sample':
            out.append(('sample', 0))
        else:
            for x in g:
                out.append(('num', int(x)) if x.isdigit() else ('let', x.lower()))
    return out


def combine_units(folder):
    """Return {unit_label: [files sorted]} for a folder. unit_label None -> single output."""
    fs = sorted(f for f in os.listdir(folder)
                if os.path.splitext(f)[1].lower() in VID)
    fs = [f for f in fs if not any(k == 'sample' for k, _ in tokens(f))]
    info = [(f, tokens(f)) for f in fs]
    if len(info) < 2:
        return {}
    # positions that vary across members (pad short rows with None)
    npos = max(len(t) for _, t in info)
    vary = [p for p in range(npos) if len({(t[p] if p < len(t) else None) for _, t in info}) > 1]
    if not vary:
        return {'': fs}  # identical tokens -> still one unit
    if len(vary) == 1:
        # single varying token = part order, one unit
        p = vary[0]
        return {'': [f for f, _ in sorted(info, key=lambda ft: ft[1][p] if p < len(ft[1]) else ('num', 0))]}
    unit_pos = vary[0]                     # first varying token = unit discriminator (disc/scene)
    units = collections.defaultdict(list)
    for f, t in info:
        u = t[unit_pos] if unit_pos < len(t) else None
        units[u].append((f, t))
    out = {}
    for u, mem in units.items():
        order_key = lambda ft: ft[1] + [(None, 0)] * (npos - len(ft[1]))
        mems = sorted(mem, key=order_key)
        label = str(u[1]) if len(units) > 1 and u else ''
        out[label] = [f for f, _ in mems]
    return out


MP4_OK = {'mpeg4', 'h264', 'hevc', 'mpeg2video', 'mjpeg'}


def vcodec(path):
    r = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                        '-show_streams', '-select_streams', 'v:0', path],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)['streams'][0].get('codec_name', '')
    except Exception:
        return ''


def concat_remux(parts, dst):
    """Lossless concat demuxer -> mp4 (video copy, audio->aac)."""
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as lf:
        for p in parts:
            lf.write("file '%s'\n" % p.replace("'", "'\\''"))
        lpath = lf.name
    try:
        cmd = [FFMPEG, '-y', '-f', 'concat', '-safe', '0', '-i', lpath,
               '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
               '-movflags', '+faststart', dst]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        return r.returncode == 0, (r.stderr or '')[-400:]
    finally:
        os.unlink(lpath)


def concat_encode(parts, dst):
    """ffmpeg concat filter -> h264/aac mp4."""
    n = len(parts)
    ins = []
    for p in parts:
        ins += ['-i', p]
    fc_in = ''.join('[%d:v]format=yuv420p[v%d];[%d:a]aresample=44100,aformat=channel_layouts=stereo[a%d];' % (i, i, i, i) for i in range(n))
    fc_cat = ''.join('[v%d][a%d]' % (i, i) for i in range(n)) + 'concat=n=%d:v=1:a=1[v][a]' % n
    cmd = [FFMPEG, '-y'] + ins + ['-filter_complex', fc_in + fc_cat,
           '-map', '[v]', '-map', '[a]',
           '-c:v', 'libx264', '-crf', '20', '-preset', 'medium',
           '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', dst]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    return r.returncode == 0, (r.stderr or '')[-400:]


def combine(parts, dst):
    """Remux when all parts are mp4-compatible, else re-encode."""
    codecs = {vcodec(p) for p in parts}
    if codecs and codecs <= MP4_OK:
        ok, tail = concat_remux(parts, dst)
        if ok:
            return ok, 'remux ' + ','.join(codecs), tail
        # demuxer failed (mismatched params) -> re-encode
        ok, tail2 = concat_encode(parts, dst)
        return ok, 'encode-fallback', tail2 if not ok else 'remuxfail:' + tail[:120]
    ok, tail = concat_encode(parts, dst)
    return ok, 'encode ' + ','.join(codecs), tail


def main():
    dry = '--dry' in sys.argv
    only = None
    for a in sys.argv:
        if a.startswith('--only='):
            only = a.split('=', 1)[1].lower()
    plan = []
    for d in sorted(os.listdir(D)):
        p = os.path.join(D, d)
        if not os.path.isdir(p):
            continue
        if only and only not in d.lower():
            continue
        units = combine_units(p)
        for label, mems in units.items():
            if len(mems) < 2:
                continue
            name = d if not label else '%s - %s' % (d, label.upper())
            plan.append((p, mems, os.path.join(D, name + '.mp4'), name))
    results = []
    for p, mems, dst, name in plan:
        print('%s  <-  %d parts' % (name, len(mems)))
        for m in mems:
            print('      %s' % m[:90])
        if dry:
            continue
        if os.path.exists(dst):
            print('      -> skip (exists)')
            continue
        ok, how, tail = combine([os.path.join(p, m) for m in mems], dst)
        size = os.path.getsize(dst) if ok and os.path.exists(dst) else 0
        print('      -> %s [%s] %s  %.1fMB' % ('OK' if ok else 'FAIL', how, os.path.basename(dst), size / 1e6))
        if not ok:
            print('      ffmpeg: %s' % tail)
        results.append({'src_dir': p, 'parts': mems, 'out': dst, 'ok': ok, 'how': how, 'size': size, 'ts': time.time()})
    if not dry and results:
        with open(os.path.join(EXP, 'oc-combine-log.jsonl'), 'a', encoding='utf-8') as fh:
            for r in results:
                fh.write(json.dumps(r) + '\n')
    print('done:', len(plan), 'units')


if __name__ == '__main__':
    main()
