# 票 16：地点池补齐用的脚本

都在 `E:/tmp/places16/` 下跑（`build.py` 在仓库根目录跑），抽取文件和中间数据不进仓库。

1. 下载 Geofabrik 的 `kanto-latest.osm.pbf` 到 `raw/`，`extract.py`（要 pyosmium、shapely）筛出有名字的要素（`pois.jsonl`）和行政区边界（`admin.wkb.json`）。
2. `cand.txt` 是人工列的候选（类别、id、查询名、note、季节、时段）。`match.py`、`grepoi.py`、`near.py` 在 `pois.jsonl` 里找对应的要素；`wdpick.py` 在 Wikidata 上搜（有限流，慢）。
3. 挑定的写进 `picks.json`（`node/…`、`way/…`、`relation/…` 或 `wd:Q…`），改用通称的写进 `names.json`。
4. `build.py` 把它们写到 `characters/places.toml` 末尾那一节（重跑会替换）：神社、公园、名所这几类带 wikidata 标签的取 Wikidata P625，其余取 OSM 要素；`area` 按行政区边界算。
5. `check16.py` 写旁注 `doubts.json`，再跑 `place_proof.py` 出校对页。
