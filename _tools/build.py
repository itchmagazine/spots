"""Itch NYC Spot Map builder.

usage:
  python3 -I build.py update <photos_dir> <tools_dir> <site_dir>
      Finds photos in <photos_dir> not yet in <tools_dir>/spots.json, reads GPS,
      converts them to JPEGs in <site_dir>/img, adds them to spots.json, and
      writes <site_dir>/index.html. Prints a JSON summary.
  python3 -I build.py scan <photos_dir> <tools_dir>
      Same detection, changes nothing. Prints a JSON summary.
  python3 -I build.py render <tools_dir> <site_dir>
      Rewrites <site_dir>/index.html from spots.json (after editing names/areas/notes).

Naming: "Spot Name a.HEIC", "Spot_Name_b.jpg" -> spot "Spot Name"; a trailing single
letter groups photos of one spot. Matching to existing spots ignores case,
spaces, underscores and dashes. File names in spots.json's "ignored" list are
never added (photos removed from the map on purpose).
"""
import sys, os, re, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageOps

EXTS = ('.heic', '.heif', '.jpg', '.jpeg', '.png')

def slug(s): return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def spot_name(stem):
    s = re.sub(r'[_\-]+', ' ', stem).strip()
    s = re.sub(r'\s+[a-zA-Z]$', '', s)            # trailing " a" / " b"
    s = re.sub(r'\s+', ' ', s).strip()
    return s or stem

def read_exif(path):
    b = open(path, 'rb').read()
    if path.lower().endswith(('.jpg', '.jpeg', '.png')):
        ex = Image.open(path).getexif()
    else:
        i = b.find(b'MM\x00*'); i = i if i >= 0 else b.find(b'II*\x00')
        if i < 0: return None, None, None
        ex = Image.Exif(); ex.load(b[i:i + 200000])
    gps = ex.get_ifd(0x8825); ifd = ex.get_ifd(0x8769)
    def dms(v, ref):
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        return -d if ref in ('S', 'W') else d
    try:
        lat = dms(gps[2], gps[1]); lon = dms(gps[4], gps[3])
    except Exception:
        lat = lon = None
    t = ifd.get(0x9003) or ex.get(0x0132)
    if t: t = t[:10].replace(':', '-') + ' ' + t[11:16]
    return lat, lon, t

def load_image(path, tmp):
    if path.lower().endswith(('.heic', '.heif')):
        import heic
        os.makedirs(tmp, exist_ok=True)
        im, _ = heic.convert(path, None, tmp)
        return im
    return ImageOps.exif_transpose(Image.open(path)).convert('RGB')

def load_state(tools):
    p = os.path.join(tools, 'spots.json')
    return json.load(open(p)) if os.path.exists(p) else {"spots": []}

def scan(photos, tools):
    st = load_state(tools)
    seen = {ph['file'] for s in st['spots'] for ph in s['photos']}
    seen |= set(st.get('ignored', []))  # photos removed from the map on purpose
    files = sorted(f for f in os.listdir(photos) if f.lower().endswith(EXTS) and not f.startswith('.'))
    return st, [f for f in files if f not in seen]

# Obstacle types read from the words in each spot's name (Sebastian's own words).
TYPES = [("Rail", r"rail|kink"), ("Hubba", r"hubba"), ("Ledge", r"ledge"), ("Gap", r"gap"),
         ("Stairs", r"stair|\bset\b|\bsteps?\b|\d+ up \d+ down|\d+ down"), ("Bank", r"bank"), ("Pad", r"\bpads?\b"),
         ("Curb", r"curb"), ("Wallride", r"wallride|ride on"), ("Bump", r"bump"), ("Drop", r"drop"),
         ("Grate", r"grate"), ("Barrier", r"barrier|barricade"), ("Ramp", r"kicker|ramp|roll in|hip|wave|transition"),
         ("Wallie", r"wallie"), ("Fence", r"fence"), ("Philly Step", r"philly"), ("Block", r"\bblocks?\b"), ("DIY", r"\bdiy\b")]

def auto_types(name):
    n = name.lower()
    out = [label for label, pat in TYPES if re.search(pat, n)]
    if "Philly Step" in out and "stair" not in n and "Stairs" in out:
        out.remove("Stairs")
    return out

def render(tools, site):
    st = load_state(tools)
    data = [{"id": s["id"], "name": s["name"], "area": s.get("area", ""), "notes": s.get("notes", ""),
             "tags": list(dict.fromkeys(s.get("tags", []) + auto_types(s["name"]))),
             "photos": [{k: p[k] for k in ("file", "src", "thumb", "lat", "lon", "time")} for p in s["photos"]]}
            for s in st["spots"]]
    os.makedirs(site, exist_ok=True)
    blob = json.dumps(data, indent=1)
    for tpl_name, out_name in (("template.html", "index.html"), ("gallery.html", "gallery.html")):
        p = os.path.join(tools, tpl_name)
        if os.path.exists(p):
            open(os.path.join(site, out_name), 'w').write(open(p).read().replace('/*SPOTS_JSON*/[]', blob))

def update(photos, tools, site):
    st, new = scan(photos, tools)
    out = {"added": [], "new_spots": [], "no_location": [], "errors": [], "new_images": []}
    os.makedirs(os.path.join(site, 'img'), exist_ok=True)
    by_key = {slug(s['name']): s for s in st['spots']}
    for f in new:
        path = os.path.join(photos, f)
        try:
            lat, lon, t = read_exif(path)
            if lat is None:
                out['no_location'].append(f); continue
            stem = os.path.splitext(f)[0]
            name = spot_name(stem); key = slug(name)
            spot = by_key.get(key)
            if not spot:
                spot = {"id": key, "name": name.title() if name.islower() else name, "area": "", "notes": "", "tags": [], "photos": []}
                st['spots'].append(spot); by_key[key] = spot; out['new_spots'].append(spot['name'])
            base = slug(stem); n = 2
            while any(p['src'] == f'img/{base}.jpg' for s in st['spots'] for p in s['photos']):
                base = f'{slug(stem)}-{n}'; n += 1
            im = load_image(path, os.path.join(site, '.tmp'))
            big = im.copy(); big.thumbnail((1400, 1400)); big.save(os.path.join(site, 'img', base + '.jpg'), quality=82, optimize=True)
            sm = im.copy(); sm.thumbnail((360, 480)); sm.save(os.path.join(site, 'img', base + '-sm.jpg'), quality=78)
            spot['photos'].append({"file": f, "src": f"img/{base}.jpg", "thumb": f"img/{base}-sm.jpg",
                                   "lat": round(lat, 6), "lon": round(lon, 6), "time": t or ""})
            out['added'].append({"file": f, "spot": spot['name']})
            out['new_images'] += [f"img/{base}.jpg", f"img/{base}-sm.jpg"]
        except Exception as e:
            out['errors'].append({"file": f, "error": str(e)})
    json.dump(st, open(os.path.join(tools, 'spots.json'), 'w'), indent=1)
    render(tools, site)
    print(json.dumps(out, indent=1))

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'update': update(*sys.argv[2:5])
    elif cmd == 'scan':
        st, new = scan(*sys.argv[2:4]); print(json.dumps({"new_files": new}, indent=1))
    elif cmd == 'render': render(*sys.argv[2:4])
