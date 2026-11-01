"""Searches Wikidata for the named sights in cand.txt and writes wdpick.txt (first hit in range)."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "eidolon-places-curation/1.0"}
KINDS = set(sys.argv[1].split(","))
S, N, W, E = 35.1, 36.1, 138.9, 140.3


def get(u):
    for k in range(6):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (k + 1))
                continue
            raise


out = open("wdpick.txt", "a", encoding="utf-8")
for line in open("cand.txt", encoding="utf-8"):
    if line.startswith("#") or "|" not in line:
        continue
    cat, pid, q, note, *_ = [x.strip() for x in line.split("|")]
    if cat not in KINDS or "跳过" in q or "占位" in note or not note:
        continue
    r = get("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": q, "language": "ja", "uselang": "ja", "format": "json",
         "limit": 7}))
    ids = [x["id"] for x in r.get("search", [])]
    best = []
    if ids:
        ents = get("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|descriptions|claims",
             "languages": "ja", "format": "json"}))["entities"]
        for i in ids:
            x = ents[i]
            c = x.get("claims", {}).get("P625")
            if not c or "datavalue" not in c[0]["mainsnak"]:
                continue
            v = c[0]["mainsnak"]["datavalue"]["value"]
            lat, lon = v["latitude"], v["longitude"]
            if not (S <= lat <= N and W <= lon <= E):
                continue
            gone = "P576" in x.get("claims", {}) or "P3999" in x.get("claims", {})
            best.append(f"{i} {x.get('labels', {}).get('ja', {}).get('value')} | "
                        f"{x.get('descriptions', {}).get('ja', {}).get('value')} | {lat:.5f},{lon:.5f}"
                        + (" | 已废止?" if gone else ""))
    print(f"{pid} [{cat}] {q}", file=out)
    for b in best[:3]:
        print("   ", b, file=out)
    if not best:
        print("    （无）", file=out)
    out.flush()
    time.sleep(0.3)
