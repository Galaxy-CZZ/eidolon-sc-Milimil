"""Pulls named POIs and admin boundaries out of the Geofabrik Kanto extract.

Writes pois.jsonl (one named feature per line: osm type/id, name, lat, lon, a few tags) and
admin.wkb.json (admin_level 4/6/7/8 polygons as hex WKB) for area lookup.
"""
import json
import osmium
import shapely.wkb
from osmium.geom import WKBFactory

SRC = "raw/kanto-latest.osm.pbf"
S, N, W, E = 35.1, 36.1, 138.9, 140.3
KEYS = ("amenity", "shop", "leisure", "tourism", "historic", "natural", "place", "landuse",
        "highway", "waterway", "man_made", "building", "railway", "public_transport", "bridge")
KEEP = ("amenity", "shop", "leisure", "tourism", "historic", "natural", "place", "highway",
        "waterway", "religion", "brand", "wikidata", "cuisine", "opening_hours", "website",
        "disused:amenity", "disused:shop", "building", "man_made", "name:en", "railway")

pois = open("pois.jsonl", "w", encoding="utf-8")
admin = []
wkb = WKBFactory()


def tags_of(o):
    return {k: o.tags[k] for k in KEEP if k in o.tags}


def interesting(o):
    t = o.tags
    if "name" not in t:
        return False
    if "boundary" in t and "amenity" not in t:
        return False
    if t.get("highway") and t["highway"] not in ("pedestrian", "living_street", "footway",
                                                   "residential", "tertiary", "secondary",
                                                   "unclassified", "primary"):
        return False
    return any(k in t for k in KEYS) or "wikidata" in t


def emit(kind, oid, name, lat, lon, tags):
    if S <= lat <= N and W <= lon <= E:
        pois.write(json.dumps({"t": kind, "id": oid, "name": name, "lat": round(lat, 6),
                               "lon": round(lon, 6), "tags": tags}, ensure_ascii=False) + "\n")


fp = osmium.FileProcessor(SRC).with_locations().with_areas()
n = 0
for o in fp:
    n += 1
    if n % 5_000_000 == 0:
        print(n, flush=True)
    if o.is_area():
        t = o.tags
        if t.get("boundary") == "administrative" and t.get("admin_level") in ("4", "6", "7", "8"):
            try:
                admin.append({"name": t.get("name"), "level": t.get("admin_level"),
                              "wkb": wkb.create_multipolygon(o)})
            except Exception:
                pass
        elif not o.from_way() and interesting(o):
            try:
                g = shapely.wkb.loads(wkb.create_multipolygon(o), hex=True)
                c = g.representative_point()
                emit("relation", o.orig_id(), t["name"], c.y, c.x, tags_of(o))
            except Exception:
                pass
        continue
    if not interesting(o):
        continue
    if o.is_node():
        emit("node", o.id, o.tags["name"], o.location.lat, o.location.lon, tags_of(o))
    elif o.is_way():
        try:
            pts = [(nd.lat, nd.lon) for nd in o.nodes if nd.location.valid()]
        except Exception:
            continue
        if pts:
            emit("way", o.id, o.tags["name"], sum(p[0] for p in pts) / len(pts),
                 sum(p[1] for p in pts) / len(pts), tags_of(o))
    elif o.is_relation():
        # relations get their point from the area pass below when they are multipolygons
        pass
pois.close()
json.dump(admin, open("admin.wkb.json", "w", encoding="utf-8"), ensure_ascii=False)
print("done", n, len(admin))
