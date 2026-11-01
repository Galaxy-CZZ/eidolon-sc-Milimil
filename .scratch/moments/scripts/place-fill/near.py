import json,sys,unicodedata
sys.stdout.reconfigure(encoding="utf-8")
def norm(s): return unicodedata.normalize("NFKC",s).replace(" ","").replace("　","").lower()
# lines: query|lat|lon
qs=[l.split("|") for l in open(sys.argv[1],encoding="utf-8").read().split("\n") if l.strip()]
pois=[json.loads(l) for l in open("pois.jsonl",encoding="utf-8")]
for q,lat,lon in qs:
    lat,lon=float(lat),float(lon); n=norm(q)
    hits=[p for p in pois if n in norm(p["name"]) and abs(p["lat"]-lat)<0.02 and abs(p["lon"]-lon)<0.025 and "bicycle" not in str(p["tags"])]
    print("==",q)
    for p in hits[:6]:
        t=p["tags"]; print("  ",f"{p['t']}/{p['id']}",p["name"],f"({p['lat']:.5f},{p['lon']:.5f})"," ".join(f"{a}={t[a]}" for a in ("amenity","shop","leisure","tourism","highway","wikidata") if a in t))
