import json,math,sys,tomllib,collections
sys.stdout.reconfigure(encoding="utf-8")
b=json.load(open("built.json",encoding="utf-8"))
picks=json.load(open("picks.json",encoding="utf-8"))
names=json.load(open("names.json",encoding="utf-8"))
src=json.load(open("coord-sources-others.json",encoding="utf-8"))
pois={}
for l in open("pois.jsonl",encoding="utf-8"):
    p=json.loads(l); pois[f"{p['t']}/{p['id']}"]=p
cache=json.load(open("wd-cache.json",encoding="utf-8"))
def km(a,b,c,d): return math.hypot((a-c)*111,(b-d)*91)
doubts={}
for x in b:
    ref=picks[x["id"]].removeprefix("osm:"); d=[]
    if not ref.startswith("wd:"):
        p=pois[ref]
        dist=km(p["lat"],p["lon"],x["lat"],x["lon"])
        if dist>0.8: d.append(f"Wikidata 坐标和 OSM 要素相差约 {dist:.1f} km")
        if x["id"] in names and names[x["id"]]!=p["name"]: d.append(f"OSM 上叫「{p['name']}」，这里写成通称")
    else:
        lab=cache[ref[3:]]["label"]
        if x["id"] in names: d.append(f"Wikidata 标签是「{lab}」，这里写成通称")
    if d: doubts[x["id"]]="；".join(d)
allp=tomllib.load(open("E:/Download/others/agent-test/eidolon-sc/characters/places.toml","rb"))["places"]
c=collections.Counter(p["name"] for p in allp)
for n,k in c.items():
    if k>1: print("重名",n)
# near duplicates
for i,p in enumerate(allp):
    for q in allp[i+1:]:
        if km(p["lat"],p["lon"],q["lat"],q["lon"])<0.15 and p["category"]!="venue" and q["category"]!="venue":
            print("很近",p["id"],q["id"],round(km(p["lat"],p["lon"],q["lat"],q["lon"]),2))
json.dump(doubts,open("doubts.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for k,v in doubts.items(): print(k,v)
print(collections.Counter(p["category"] for p in allp), len(allp))
