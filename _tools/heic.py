import struct, sys, subprocess, os, glob
from PIL import Image
def boxes(b, s, e):
    while s < e:
        size, typ = struct.unpack('>I4s', b[s:s+8]); h = 8
        if size == 1: size = struct.unpack('>Q', b[s+8:s+16])[0]; h = 16
        if size == 0: size = e - s
        yield typ.decode('latin1'), s+h, s+size
        s += size
def fullbox(b, s): return b[s], int.from_bytes(b[s+1:s+4],'big'), s+4
def parse(path):
    b = open(path,'rb').read()
    top = {t:(s,e) for t,s,e in boxes(b,0,len(b))}
    ms, me = top['meta']; _,_,ms = fullbox(b, ms)
    mb = {t:(s,e) for t,s,e in boxes(b,ms,me)}
    # pitm
    v,f,p = fullbox(b, mb['pitm'][0]); primary = struct.unpack('>H', b[p:p+2])[0] if v==0 else struct.unpack('>I', b[p:p+4])[0]
    # iinf
    v,f,p = fullbox(b, mb['iinf'][0]); n = struct.unpack('>H' if v==0 else '>I', b[p:p+(2 if v==0 else 4)])[0]; p += 2 if v==0 else 4
    types = {}
    for t,s,e in boxes(b,p,mb['iinf'][1]):
        v2,f2,q = fullbox(b,s)
        iid = struct.unpack('>H', b[q:q+2])[0] if v2<3 else struct.unpack('>I', b[q:q+4])[0]
        q += 2 if v2<3 else 4; q += 2
        types[iid] = b[q:q+4].decode('latin1')
    # iloc
    v,f,p = fullbox(b, mb['iloc'][0])
    os_, ls = b[p]>>4, b[p]&15; bos, isz = b[p+1]>>4, b[p+1]&15; p += 2
    rd = lambda n_: (int.from_bytes(b[p:p+n_],'big') if n_ else 0)
    cnt = struct.unpack('>H' if v<2 else '>I', b[p:p+(2 if v<2 else 4)])[0]; p += 2 if v<2 else 4
    loc = {}
    for _ in range(cnt):
        iid = struct.unpack('>H' if v<2 else '>I', b[p:p+(2 if v<2 else 4)])[0]; p += 2 if v<2 else 4
        cm = (struct.unpack('>H', b[p:p+2])[0] & 15) if v in (1,2) else 0
        if v in (1,2): p += 2
        p += 2
        base = rd(bos); p += bos
        ec = struct.unpack('>H', b[p:p+2])[0]; p += 2
        exts = []
        for _ in range(ec):
            if v in (1,2) and isz: p += isz
            off = rd(os_); p += os_; ln = rd(ls); p += ls
            exts.append((base+off, ln))
        if cm == 1: exts = [(mb['idat'][0]+o, l) for o,l in exts]
        loc[iid] = exts
    data = lambda iid: b''.join(b[o:o+l] for o,l in loc[iid])
    # iprp
    ip = {t:(s,e) for t,s,e in boxes(b,*mb['iprp'])}
    props = [(t,s,e) for t,s,e in boxes(b,*ip['ipco'])]
    v,f,p = fullbox(b, ip['ipma'][0]); ec = struct.unpack('>I', b[p:p+4])[0]; p += 4
    assoc = {}
    for _ in range(ec):
        iid = struct.unpack('>H' if v<1 else '>I', b[p:p+(2 if v<1 else 4)])[0]; p += 2 if v<1 else 4
        k = b[p]; p += 1; lst = []
        for _ in range(k):
            if f & 1: x = struct.unpack('>H', b[p:p+2])[0] & 0x7fff; p += 2
            else: x = b[p] & 0x7f; p += 1
            lst.append(x)
        assoc[iid] = lst
    def prop(iid, name):
        for x in assoc.get(iid, []):
            if x and props[x-1][0] == name: return props[x-1]
    # iref dimg
    v,f,p = fullbox(b, mb['iref'][0]); refs = {}
    for t,s,e in boxes(b,p,mb['iref'][1]):
        w = 2 if v==0 else 4
        frm = int.from_bytes(b[s:s+w],'big'); c = struct.unpack('>H', b[s+w:s+w+2])[0]
        refs.setdefault(t,{})[frm] = [int.from_bytes(b[s+w+2+i*w:s+w+2+(i+1)*w],'big') for i in range(c)]
    assert types[primary] == 'grid', types[primary]
    g = data(primary); large = g[1] & 1
    rows, cols = g[2]+1, g[3]+1
    W = int.from_bytes(g[4:6+2*large],'big'); H = int.from_bytes(g[6+2*large:8+4*large],'big')
    tiles = refs['dimg'][primary]
    rot = prop(primary,'irot'); rot = b[rot[1]] & 3 if rot else 0
    return b, data, prop, tiles, rows, cols, W, H, rot
def hvcc_nals(b, s, e):
    p = s + 22; na = b[p]; p += 1; out = b''
    for _ in range(na):
        p += 1; nn = struct.unpack('>H', b[p:p+2])[0]; p += 2
        for _ in range(nn):
            l = struct.unpack('>H', b[p:p+2])[0]; p += 2
            out += b'\x00\x00\x00\x01' + b[p:p+l]; p += l
    return out
def annexb(d):
    out = b''; p = 0
    while p < len(d):
        l = struct.unpack('>I', d[p:p+4])[0]; out += b'\x00\x00\x00\x01' + d[p+4:p+4+l]; p += 4+l
    return out
def convert(path, outpath, tmp):
    b, data, prop, tiles, rows, cols, W, H, rot = parse(path)
    hv = prop(tiles[0], 'hvcC'); hdr = hvcc_nals(b, hv[1], hv[2])
    stream = b''.join(hdr + annexb(data(t)) for t in tiles)
    open(f'{tmp}/s.hevc','wb').write(stream)
    for x in glob.glob(f'{tmp}/t_*.png'): os.remove(x)
    subprocess.run(['ffmpeg','-loglevel','error','-y','-f','hevc','-i',f'{tmp}/s.hevc','-fps_mode','passthrough',f'{tmp}/t_%04d.png'], check=True)
    fr = sorted(glob.glob(f'{tmp}/t_*.png')); assert len(fr) == len(tiles), (len(fr), len(tiles))
    tw, th = Image.open(fr[0]).size
    canvas = Image.new('RGB', (cols*tw, rows*th))
    for i, x in enumerate(fr): canvas.paste(Image.open(x).convert('RGB'), ((i%cols)*tw, (i//cols)*th))
    canvas = canvas.crop((0,0,W,H))
    if rot: canvas = canvas.rotate(90*rot, expand=True)
    return canvas, rot
