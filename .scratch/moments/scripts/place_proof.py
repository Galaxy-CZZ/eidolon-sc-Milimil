"""Writes E:/tmp/places16/proof.html: the place pool, grouped by category, the idols' place_likes and the jobs'
places, for the maintainer to proofread. Run from the repository root."""
import html
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(".")
OUT = Path("E:/tmp/places16/proof.html")
SIDECARS = (Path("E:/tmp/places15"), Path("E:/tmp/places16"))

KINDS = {
    "cafe": "咖啡馆·甜品·餐厅", "park": "公园·河边", "shrine": "神社·寺", "shopping-street": "商店街",
    "fashion-street": "杂货·服装街区", "books": "书店·图书馆", "mall": "商场·车站大楼",
    "seaside": "海边·湾岸", "amusement": "水族馆·动物园·游乐园", "museum": "美术馆·博物馆·天象仪",
    "night-view": "展望台·夜景", "bath": "温泉·钱汤", "seasonal": "季节名所", "venue": "演出场馆",
    "nearby": "近郊（东京都以外，哪类都行）",
}
SEASONS = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
SLOTS = {"morning": "上午", "afternoon": "下午", "evening": "晚上"}

places = tomllib.loads((ROOT / "characters/places.toml").read_text(encoding="utf-8"))["places"]
characters = tomllib.loads((ROOT / "characters/characters.toml").read_text(encoding="utf-8"))["characters"]
jobs = tomllib.loads((ROOT / "characters/jobs.toml").read_text(encoding="utf-8"))["jobs"]
names = {c["id"]: c["name"] for c in characters}

coords: dict[str, str] = {}
for here in SIDECARS:
    for f in ("coord-sources-venues.json", "coord-sources-pilgrimage.json", "coord-sources-others.json"):
        if (here / f).exists():
            coords |= json.loads((here / f).read_text(encoding="utf-8"))

doubts: dict[str, str] = {}
for here in SIDECARS:
    if (here / "doubts.json").exists():
        doubts |= json.loads((here / "doubts.json").read_text(encoding="utf-8"))

e = html.escape


def links(text: str) -> str:
    out, last = [], 0
    for m in re.finditer(r"https?://[^\s；;、，）)]+", text):
        out.append(e(text[last:m.start()]))
        out.append(f'<a href="{e(m[0])}" target="_blank">{e(m[0])}</a>')
        last = m.end()
    return "".join(out) + e(text[last:])


def coord_link(source: str) -> str:
    m = re.match(r"Wikidata (Q\d+)", source)
    if m:
        return f'<a href="https://www.wikidata.org/wiki/{m[1]}" target="_blank">{e(source)}</a>'
    m = re.match(r"OSM (node|way|relation) (\d+)", source)
    if m:
        return f'<a href="https://www.openstreetmap.org/{m[1]}/{m[2]}" target="_blank">{e(source)}</a>'
    return e(source)


rows = []
for kind, title in KINDS.items():
    group = [p for p in places if p["category"] == kind]
    if not group:
        continue
    rows.append(f'<h2 id="{e(kind)}">{e(title)}（{len(group)}）</h2><table><tr><th>#</th><th>地名 / id</th>'
                "<th>区</th><th>类别</th><th>说明</th><th>偶像</th><th>出处</th><th>季节·时段</th>"
                "<th>地图</th><th>坐标来源</th><th>拿不准的</th></tr>")
    for i, p in enumerate(sorted(group, key=lambda p: (not p.get("source"), p["area"])), 1):
        lat, lon = p["lat"], p["lon"]
        osm = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}"
        gmap = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        amap = f"https://uri.amap.com/marker?position={lon},{lat}&name={e(p['name'])}"
        when = " ".join([SEASONS[s] for s in p.get("seasons", [])] + [SLOTS[s] for s in p.get("slots", [])])
        extra = ""
        if p.get("venues"):
            extra = "<br><small>演出里写作：" + "、".join(e(v) for v in p["venues"]) + "</small>"
        rows.append(
            f"<tr><td>{i}</td><td><b>{e(p['name'])}</b>{' <span class=holy>圣地</span>' if p.get('source') else ''}{extra}<br><code>{e(p['id'])}</code></td>"
            f"<td>{e(p['area'])}</td><td>{e(KINDS[p['category']])}</td><td>{e(p['note'])}</td>"
            f"<td>{'、'.join(e(names.get(i, i)) for i in p.get('idols', []))}</td>"
            f"<td class=src>{links(p.get('source', ''))}</td><td>{e(when)}</td>"
            f'<td><a href="{osm}" target="_blank">OSM</a> · <a href="{gmap}" target="_blank">Google</a>'
            f' · <a href="{amap}" target="_blank">高德</a><br><small>{lat}, {lon}</small></td>'
            f"<td>{coord_link(coords.get(p['id'], '（未记）'))}</td>"
            f"<td class=doubt>{e(doubts.get(p['id'], ''))}</td></tr>"
        )
    rows.append("</table>")

likes = ['<h2 id="likes">偶像的 place_likes</h2><table><tr><th>偶像</th><th>偏好的类别</th></tr>']
for c in characters:
    if "place_likes" in c:
        likes.append(f"<tr><td>{e(c['name'])} <code>{e(c['id'])}</code></td>"
                     f"<td>{'、'.join(e(KINDS[k]) for k in c['place_likes'])}</td></tr>")
likes.append("</table>")

job_rows = ['<h2 id="jobs">工作的 places</h2><table><tr><th>工作</th><th>说明</th><th>会去的类别</th></tr>']
for j in jobs:
    kinds = "、".join(e(KINDS[k]) for k in j["places"]) if "places" in j else '<span class=none>不写（不带地名）</span>'
    job_rows.append(f"<tr><td>{e(j['name'])} <code>{e(j['id'])}</code></td><td>{e(j['note'])}</td><td>{kinds}</td></tr>")
job_rows.append("</table>")

counts = {}
for p in places:
    counts[p["category"]] = counts.get(p["category"], 0) + 1
nav = "".join(f'<a href="#{k}">{e(KINDS[k])}</a>' for k in KINDS if k in counts)
summary = "、".join(f"{KINDS[k]} {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))

OUT.write_text(f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>地点池校对（票 16）</title>
<style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:24px;color:#222;line-height:1.5}}
table{{border-collapse:collapse;width:100%;margin-bottom:32px;font-size:14px}}
th,td{{border:1px solid #ddd;padding:6px 8px;vertical-align:top;text-align:left}}
th{{background:#f4f4f4;position:sticky;top:0}} tr:nth-child(even) td{{background:#fafafa}}
code{{color:#888;font-size:12px}} .src{{max-width:340px;word-break:break-all;font-size:12px}}
.none{{color:#aaa}} .holy{{color:#fff;background:#c0392b;font-size:11px;padding:0 4px;border-radius:3px}} .doubt{{color:#a15c00;font-size:12px;max-width:260px}} nav a{{margin-right:16px}}
</style>
<h1>地点池校对（票 16：按类别）</h1>
<p>共 {len(places)} 处：{summary}。每条的「地图」三家都能点开；「坐标来源」点开是 Wikidata 条目或 OSM 要素。</p>
<nav>{nav}<a href="#likes">place_likes</a><a href="#jobs">工作的 places</a></nav>
{''.join(rows)}{''.join(likes)}{''.join(job_rows)}
</html>""", encoding="utf-8")
print(OUT)
