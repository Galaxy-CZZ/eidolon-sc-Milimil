"""Looks every candidate in cand.txt up in pois.jsonl and writes match.txt for picking."""
import json
import unicodedata

def norm(s):
    return unicodedata.normalize("NFKC", s).replace(" ", "").replace("・", "").replace("　", "").lower()

pois = [json.loads(l) for l in open("pois.jsonl", encoding="utf-8")]
by = {}
for p in pois:
    by.setdefault(norm(p["name"]), []).append(p)

def show(p):
    t = p["tags"]
    keys = [f"{k}={t[k]}" for k in ("amenity", "shop", "leisure", "tourism", "historic", "natural",
                                     "place", "highway", "religion", "brand", "wikidata",
                                     "disused:amenity", "disused:shop") if k in t]
    return f"  {p['t']}/{p['id']} {p['name']} ({p['lat']:.5f},{p['lon']:.5f}) {' '.join(keys)}"

out = open("match.txt", "w", encoding="utf-8")
for line in open("cand.txt", encoding="utf-8"):
    if line.startswith("#") or "|" not in line:
        continue
    cat, pid, q, note, *_ = [x.strip() for x in line.split("|")]
    if "跳过" in q or "占位" in note or not note:
        continue
    n = norm(q)
    hits = by.get(n, [])
    kind = "exact"
    if not hits:
        kind = "partial"
        hits = [p for k, ps in by.items() if (n in k and len(k) <= len(n) + 12) for p in ps]
        if not hits:
            kind = "token"
            toks = sorted((norm(t) for t in q.replace("・", " ").split()), key=len, reverse=True)
            for t in toks + [n.removesuffix("本店").removesuffix("店")[:6]]:
                if len(t) < 2:
                    continue
                hits = [p for k, ps in by.items() if t in k and len(k) <= len(t) + 14 for p in ps]
                if hits:
                    break
        hits.sort(key=lambda p: (not any(k in p["tags"] for k in ("amenity", "shop", "tourism", "leisure")), len(p["name"])))
    print(f"{pid} [{cat}] {q}: {kind} {len(hits)}", file=out)
    for p in hits[:8]:
        print(show(p), file=out)
