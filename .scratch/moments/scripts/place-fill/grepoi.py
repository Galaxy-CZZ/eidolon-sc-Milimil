import json,sys,unicodedata
sys.stdout.reconfigure(encoding="utf-8")
def norm(s): return unicodedata.normalize("NFKC",s).replace(" ","").replace("　","").lower()
qs=[norm(q) for q in open(sys.argv[1],encoding="utf-8").read().split("\n") if q.strip()]
BAD=("bicycle","parking","hairdresser","doctors","pharmacy","dentist","kindergarten","school","apartment","clinic","massage","laundry","nightclub","brothel","pub","bar")
for l in open("pois.jsonl",encoding="utf-8"):
    p=json.loads(l); n=norm(p["name"]); t=p["tags"]
    if any(t.get(a) in BAD for a in ("amenity","shop","tourism")): continue
    for q in qs:
        if q in n and len(n)<=len(q)+20:
            k=" ".join(f"{a}={t[a]}" for a in ("amenity","shop","leisure","tourism","highway","wikidata","brand") if a in t)
            print(q,"|",f"{p['t']}/{p['id']}",p["name"],f"({p['lat']:.5f},{p['lon']:.5f})",k)
