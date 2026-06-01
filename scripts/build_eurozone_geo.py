#!/usr/bin/env python3
"""Build simplified eurozone SVG paths from Natural Earth 50m (public domain).
Output: JS module docs/design/prototype/scenes/_eurozone-geo.js
  { VIEWBOX, GEO:{ISO:{d,cx,cy}}, CONTEXT:{ISO:d} }
  - GEO     = les 21 pays de la zone euro (cliquables, labellisés, remplis par état).
  - CONTEXT = pays européens voisins (UK, Scandinavie, Pologne, Suisse, Balkans…)
              dessinés en fond muet pour ne pas amputer l'Europe. Même transform que
              GEO (cadrage centré sur la zone euro) → le contexte déborde/clip aux bords.

Source (domaine public, télécharger d'abord vers /tmp/ne50.geojson) :
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
Puis : python3 scripts/build_eurozone_geo.py  (chemins en dur ci-dessous, proto local)."""
import json, math

EURO = {'AT','BE','BG','CY','DE','EE','ES','FI','FR','GR','HR','IE','IT',
        'LT','LU','LV','MT','NL','PT','SI','SK'}
# fenêtre euro (drop des territoires d'outre-mer : Guyane, Canaries, Açores, Réunion…)
E_LON_MIN,E_LON_MAX,E_LAT_MIN,E_LAT_MAX = -25,40,34,72
# fenêtre contexte (voisins à dessiner derrière) — un peu plus large
C_LON_MIN,C_LON_MAX,C_LAT_MIN,C_LAT_MAX = -12,34,30,71
W = 400.0
PAD = 14
LAT0 = 52.0
K = math.cos(math.radians(LAT0))
def proj(lon,lat): return (lon*K, -lat)

d = json.load(open('/tmp/ne50.geojson'))

def collect(window, want_euro):
    lo0,lo1,la0,la1 = window
    rings = {}
    for ft in d['features']:
        p = ft['properties']
        iso = p.get('ISO_A2_EH') or p.get('ISO_A2')
        if not iso or iso == '-99': continue
        if (iso in EURO) != want_euro: continue
        geom = ft['geometry']
        polys = geom['coordinates'] if geom['type']=='MultiPolygon' else [geom['coordinates']]
        for poly in polys:
            ext = poly[0]
            clon = sum(c[0] for c in ext)/len(ext); clat = sum(c[1] for c in ext)/len(ext)
            if not (lo0<=clon<=lo1 and la0<=clat<=la1): continue
            rings.setdefault(iso, []).append([proj(*c) for c in ext])
    return rings

euro = collect((E_LON_MIN,E_LON_MAX,E_LAT_MIN,E_LAT_MAX), True)
ctx  = collect((C_LON_MIN,C_LON_MAX,C_LAT_MIN,C_LAT_MAX), False)

# transform = bbox des seuls pays EURO (cadrage centré zone euro)
xs=[x for rs in euro.values() for r in rs for x,y in r]
ys=[y for rs in euro.values() for r in rs for x,y in r]
minx,maxx,miny,maxy=min(xs),max(xs),min(ys),max(ys)
scale=(W-2*PAD)/(maxx-minx)
H=round((maxy-miny)*scale+2*PAD)
def tx(x): return (x-minx)*scale+PAD
def ty(y): return (y-miny)*scale+PAD

def area(r):
    a=0
    for i in range(len(r)):
        x1,y1=r[i]; x2,y2=r[(i+1)%len(r)]; a+=x1*y2-x2*y1
    return abs(a)/2
def simplify(r,eps):
    out=[r[0]]
    for pt in r[1:]:
        if (pt[0]-out[-1][0])**2+(pt[1]-out[-1][1])**2>=eps*eps: out.append(pt)
    return out if len(out)>=3 else r
def to_paths(rings, min_area, eps, with_centroid):
    res={}
    for iso,rs in rings.items():
        vr=[[(round(tx(x),1),round(ty(y),1)) for x,y in r] for r in rs]
        areas=[area(r) for r in vr]; big=max(areas)
        kept=[simplify(r,eps) for r,a in zip(vr,areas) if a>=min_area or a==big]
        dpath=" ".join("M "+" L ".join(f"{x} {y}" for x,y in r)+" Z" for r in kept)
        if with_centroid:
            main=max(kept,key=area)
            cx=round(sum(x for x,y in main)/len(main),1); cy=round(sum(y for x,y in main)/len(main),1)
            res[iso]={"d":dpath,"cx":cx,"cy":cy}
        else:
            res[iso]=dpath
    return res

GEO = to_paths(euro, 2.5, 1.6, True)
CONTEXT = to_paths(ctx, 6.0, 2.4, False)   # contexte = plus grossier, moins d'îles

out = ("// AUTO-GÉNÉRÉ depuis Natural Earth 50m (domaine public) via scripts/build_eurozone_geo.py.\n"
       "// GEO = 21 pays zone euro (cliquables) ; CONTEXT = voisins européens (fond muet).\n"
       "// Projection équirect (lon×cos52°), cadrage centré zone euro. Ne pas éditer à la main.\n"
       f"export const VIEWBOX = '0 0 {int(W)} {H}';\n"
       "export const GEO = " + json.dumps(GEO, ensure_ascii=False, separators=(',',':')) + ";\n"
       "export const CONTEXT = " + json.dumps(CONTEXT, ensure_ascii=False, separators=(',',':')) + ";\n")
open('/Users/musubi42/Documents/Musubi42/bizz/Eurio/docs/design/prototype/scenes/_eurozone-geo.js','w').write(out)
print('viewBox 0 0', int(W), H)
print('GEO:', len(GEO), 'pays |', sorted(GEO))
print('CONTEXT:', len(CONTEXT), 'pays |', sorted(CONTEXT))
