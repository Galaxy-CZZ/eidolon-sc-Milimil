"""Builds the ticket-16 places from cand.txt + picks.json and appends them to places.toml.

picks.json: {id: "node/123" | "way/123" | "relation/123" | "wd:Q123"}. For OSM picks that carry
a wikidata tag and are shrines, parks or other named sights, the coordinate comes from Wikidata
P625; otherwise from the OSM feature. The area comes from the admin polygons in the extract.
Run from the repository root.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import shapely.wkb
from shapely.geometry import Point
from shapely.strtree import STRtree

HERE = Path("E:/tmp/places16")
PLACES = Path("characters/places.toml")
MARK = "\n# 其余各类（小店取自 OSM，神社、公园、名所取自 Wikidata）\n"
ORDER = ["spring", "summer", "autumn", "winter"], ["morning", "afternoon", "evening"]
WD_KINDS = {"park", "shrine", "seasonal", "museum", "amusement", "night-view", "seaside",
            "shopping-street", "fashion-street", "mall"}
UA = {"User-Agent": "eidolon-places-curation/1.0"}
CACHE = HERE / "wd-cache.json"

cands = {}
order = []
for line in open(HERE / "cand.txt", encoding="utf-8"):
    if line.startswith("#") or "|" not in line:
        continue
    cat, pid, q, note, seasons, slots = [x.strip() for x in line.split("|")]
    cands[pid] = dict(category=cat, query=q, note=note, seasons=[s for s in seasons.split(",") if s],
                      slots=[s for s in slots.split(",") if s])
    order.append(pid)
picks = json.loads((HERE / "picks.json").read_text(encoding="utf-8"))
names = json.loads((HERE / "names.json").read_text(encoding="utf-8")) if (HERE / "names.json").exists() else {}
notes = json.loads((HERE / "notes.json").read_text(encoding="utf-8")) if (HERE / "notes.json").exists() else {}

pois = {}
for l in open(HERE / "pois.jsonl", encoding="utf-8"):
    p = json.loads(l)
    pois[f"{p['t']}/{p['id']}"] = p

admin = json.loads((HERE / "admin.wkb.json").read_text(encoding="utf-8"))
geoms = [shapely.wkb.loads(a["wkb"], hex=True) for a in admin]
tree = STRtree(geoms)

cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def wd(qid):
    if qid not in cache:
        u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": qid, "props": "labels|claims", "languages": "ja",
             "format": "json"})
        e = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
        x = e["entities"][qid]
        c = x.get("claims", {}).get("P625")
        v = c[0]["mainsnak"]["datavalue"]["value"] if c else None
        cache[qid] = {"label": x.get("labels", {}).get("ja", {}).get("value"),
                      "coord": [v["latitude"], v["longitude"]] if v else None}
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(0.5)
    return cache[qid]


def prefetch(qids):
    todo = [q for q in dict.fromkeys(qids) if q not in cache]
    for i in range(0, len(todo), 40):
        u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(todo[i:i + 40]), "props": "labels|claims",
             "languages": "ja", "format": "json"})
        for k in range(8):
            try:
                e = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
                break
            except urllib.error.HTTPError as err:
                if err.code != 429:
                    raise
                time.sleep(15 * (k + 1))
        for qid, x in e["entities"].items():
            c = x.get("claims", {}).get("P625")
            v = c[0]["mainsnak"].get("datavalue", {}).get("value") if c else None
            cache[qid] = {"label": x.get("labels", {}).get("ja", {}).get("value"),
                          "coord": [v["latitude"], v["longitude"]] if v else None}
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(2)


need = []
for pid, ref in picks.items():
    if ref.startswith("wd:"):
        need.append(ref[3:])
    elif not ref.startswith("osm:") and cands[pid]["category"] in WD_KINDS and pois[ref]["tags"].get("wikidata"):
        need.append(pois[ref]["tags"]["wikidata"].split(";")[0])
prefetch(need)


def area(lat, lon):
    pt = Point(lon, lat)
    found = {}
    for i in tree.query(pt):
        if geoms[i].contains(pt):
            found.setdefault(admin[i]["level"], admin[i]["name"])
    pref, gun, city, ward = found.get("4"), found.get("6"), found.get("7"), found.get("8")
    local = (gun or "") + (city or "") if gun and city and not city.endswith(("市", "区")) else city
    if city and ward and city.endswith("市"):
        local = city + ward
    if pref in ("東京都", None):
        return local
    return f"{pref}{local}"


out, sources = [], {}
for pid in order:
    if pid not in picks:
        continue
    c, ref = cands[pid], picks[pid]
    if ref.startswith("wd:"):
        qid = ref[3:]
        w = wd(qid)
        lat, lon = w["coord"]
        name, src = w["label"], f"Wikidata {qid}"
    else:
        own = ref.startswith("osm:")  # Wikidata's point is wrong here: keep the OSM feature's
        ref = ref.removeprefix("osm:")
        p = pois[ref]
        name, lat, lon = p["name"], p["lat"], p["lon"]
        src = "OSM " + ref.replace("/", " ")
        qid = p["tags"].get("wikidata", "").split(";")[0]
        if qid and c["category"] in WD_KINDS and not own:
            w = wd(qid)
            if w["coord"]:
                lat, lon = w["coord"]
                src = f"Wikidata {qid}（OSM {ref.replace('/', ' ')}）"
    name = names.get(pid, name)
    lat, lon = round(lat, 5), round(lon, 5)
    sources[pid] = src
    out.append(dict(id=pid, name=name, area=area(lat, lon), lat=lat, lon=lon, category=c["category"],
                    note=notes.get(pid, c["note"]), seasons=c["seasons"], slots=c["slots"]))

q = lambda s: json.dumps(s, ensure_ascii=False)
text = PLACES.read_text(encoding="utf-8").split(MARK)[0].rstrip("\n") + "\n"
body = [MARK]
for s in out:
    e = f"\n[[places]]\nid = {q(s['id'])}\nname = {q(s['name'])}\narea = {q(s['area'])}\n"
    e += f"lat = {s['lat']}\nlon = {s['lon']}\ncategory = {q(s['category'])}\nnote = {q(s['note'])}\n"
    e += "checked = 2026-10-31\n"
    for field, o in zip(("seasons", "slots"), ORDER):
        if s[field]:
            e += f"{field} = [{', '.join(q(v) for v in o if v in s[field])}]\n"
    body.append(e)
PLACES.write_text(text + "".join(body), encoding="utf-8", newline="\n")
(HERE / "coord-sources-others.json").write_text(json.dumps(sources, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
(HERE / "built.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(out))
