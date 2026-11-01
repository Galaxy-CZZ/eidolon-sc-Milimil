# 17: 动态里的地点

**What to build:** 日常那条动态下面的 Meta 一行多一个真实的地名（日文原名）。点开地名，会在新标签页里看到地图上的那个点。地图用哪一家由部署者在后台选：OpenStreetMap、Google 或高德。地点从地点池里挑，按她的喜好和圣地加权，30 天里不重复；在家、在宿舍时不带地名。规格见 `../spec.md`：「写一条动态」里讲地点候选和规则、输出格式、写坏了；「部署者的设定」「存储」「接口」「前端」里讲地点的几处。

**Blocked by:** 14, 15

**Status:** done

- [x] **挑候选**写成纯函数，给定输入和随机源，返回最多 4 个候选，外加「不带地名」：
  - 日常那条：全部类别都可以挑。按 `place_likes` 加权；`idols` 里有她的圣地也加权。权重都是代码常量。工作那条由 19 接上。
  - 只挑当季的 `seasons`，并且符合发布时段的 `slots`。写了 `slots` 的地点，深夜（0–6 点）不挑。
  - 30 天内这位用户的动态用过的地点，一律排除。
  - 演出场馆只在 `today_lines` 里有她往年今天的演出时加进来，按名字对上那场演出的 `venue`。
  - 候选不够 4 个时，有几个给几个。
- [x] **提示词**：靠后那条系统消息里，在「最近 5 条」后面加一节「地点候选」，每个候选写 id、地名、区、一句说明。规则加上几条：
  - 只能从候选里挑，否则写 none；在家、在宿舍时写 none。
  - 正文里提不提地名随她，要提就用日文自然地提。
  - 圣地只借景，不说「这是我那张卡拍的地方」。
- [x] **解析** `<place>候选 id 或 none</place>`：写的不在候选里就不带地名，不随机补，记一次降级。
- [x] **降级记进运行记录**：这一张开始写 14 留下的那个字段，只记部分的名字和条数，不记内容。后面的票照这个写法加。
- [x] **存一份副本**：动态里存地点 id，连同地名和坐标的副本。维护者以后改名、删掉条目，已经发出的动态照旧显示原来的。
- [x] **后台**：「朋友圈」一项加「地图」字段，可选 OpenStreetMap（默认）、Google Maps、高德，整个部署统一一家。地图链接都直接用 WGS-84 坐标，不要 key：
  - OpenStreetMap：带标记的 openstreetmap.org 链接。
  - Google：官方的 Maps URLs。
  - 高德：`uri.amap.com/marker`，带经纬度和地名。
- [x] **时间线接口**：地点给出地名，和按部署者选的那家拼好的地图链接；没有地点时为空。
- [x] **前端**：Meta 一行写成「时间 · 地名」。没有地名时，连同分隔点一起省掉。点开地名在新标签页打开地图，链接加 `rel="noopener noreferrer"`。`moments.test.ts` 补上这一行的几种情形。
- [x] **测试**：
  - 挑候选的纯函数：用 `FakeRandom` 逐个给数，测加权、季节、时段、深夜、30 天排除、演出场馆只在有演出时出现、候选不够的情形。
  - 经过「跑一遍」：请求里有候选这一节和规则；写对了存下地名和坐标；写错了不带、记一次降级；改了地点池以后，已经发出的照旧显示；30 天内用过的不再出现在候选里。
  - 接口里地图链接按三家的格式各拼一次；后台设定的保存和校验。
- [x] **验收**：在本地构建版上造一条带地名的动态，用 Playwright 看 Meta 一行，点开链接确认是新标签页、地图上标对了点。三家的链接各点一次。
- [x] 表结构有改动的话，部署前手动备份数据库。（没改：`moments` 的 `place_*` 四列和运行记录的 `degraded` 列票 14 已建好）
- [x] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

## Comments

### 票 17 交接

- **地点池现在只校验**：`assembly.build` 里调了 `load_place_pool(places_path(...), characters)`，结果没存，要接上存进 `Backend` 或传给跑一遍的模块。
- **`Place` 上能直接用的**：
  - `category`、`nearby`（近郊，`area` 以三个县名之一开头）、`venue_names`（演出那天 `today_lines` 里的场馆名，按它对）。
  - `seasons`、`slots`（None 是不限）、`idols`；`source` 不是 None 的就是圣地。
- **模块级常量**：`INDOOR`（室内 6 类，下雨下雪只挑这几类）、`NEARBY`。
- **工作的 `places`**：`ListedJob.places` 是 None 就不带地名。
  - 里面有 `"nearby"` 就是任何一类，但只挑 `place.nearby` 的。
  - 「做喜欢的事」列出了全部 13 类。
- **`Character.place_likes`**：None 是没写（はづき）。
- **季节和时段**：模块里只定义了取值，没有「某月是哪季」的函数，按规格（3–5 春……）在挑候选的纯函数里写。

### 实现说明（票 17）

- **挑候选**：`moment_draws.draw_places(places, character_id, likes, venues, at, used, random)`，常量 `CANDIDATES=4`、`LIKED=3`、`HOLY=4`（两者相乘）、`KEPT_APART=30 天`；季节按东京月份，时段按东京的钟点（0–6 点是深夜，写了 `slots` 的不挑）。加权抽签和别的抽签一样每次向随机源要 `PLACES=1000` 以内的数。
- **往年今天的场馆**：`today.venues_on_this_day(now, character, world)`，和 `today_lines` 用同一个 `_days_on_this_day` 找那几天。
- **提示词**：`PostMaterial.places`；靠后那条系统消息的最后一节「# 地点候选」，每行 `- id：地名（区）说明`，她的圣地（有 `source`、`idols` 里有她）行尾加 `HOLY_SITE`「（你的卡面在这里拍过）」；没有候选时写「这次没有候选，写 none」。`POST_RULES` 加了三条规则和 `<place>` 的格式。
- **解析**：`parse_post(written, places)` 返回的 `Post` 多了 `place`（`Place` 或 None）和 `degraded`（`{"place": 1}` 或空）。`Moments._post` 把 `degraded` 写进 `Recording.degraded`（为空时记 NULL）。
- **存储和接口**：`_add_moment` 存 `place_id`、`place_name`、`place_lat`、`place_lon` 副本；时间线读副本，`Moment.shown(map_site)` 给 `{"name", "map"}`；`moments.map_link`（OSM `mlat/mlon#map=17/…`、Google Maps URLs `search/?api=1&query=lat,lon`、高德 `marker?position=lon,lat&name=…&coordinate=wgs84`）。`assembly` 把读出的地点池传给 `Moments`。
- **后台**：`MomentSettings.map`（`config.MapSite`、`MAP_SITES`、`DEFAULT_MAP_SITE="osm"`）；`_Moments` 多了 `map` 字段；`MomentsInput.map` 可省，省了不改（`_change` 里去掉 None，同 `region`）。前端「朋友圈」卡多一个「地图」下拉（`MAP_SITES`、`mapSites` 文案）。
- **前端**：`lib/moments.metaParts` 返回带 `kind` 的几段（时间、地名），`MomentsPage` 用「 · 」连；地名是 `target="_blank" rel="noopener noreferrer"` 的链接，muted，悬停变前景色加下划线。DESIGN.md「朋友圈页」改了这一行的写法。
- **判断**：
  - 对上往年今天演出的场馆一定进候选、排在最前（仍受 30 天排除和季节、时段限制），其余 4 个以内的名额再加权抽。规格只说「加进来」。
  - 候选不为空、她却没写 `<place>`，也算一次降级；没有候选时没写不算。
  - `idols` 里有她就按 `HOLY` 加权，不看有没有 `source`（规格「挑候选时给 `idols` 里的偶像加权」）；提示词里只给有 `source` 的标「卡面在这里拍过」。
  - 30 天排除按这位用户所有角色的动态算，`posted_at` 在 30 天内的都算。
- **验收**：本地库副本上插了一条带地名、一条不带地名的动态，构建版上 Playwright 看到 Meta 一行「1 小时前 · 井の頭恩賜公園」和「3 小时前」；后台依次换成三家，点地名都在新标签页打开（`window.opener` 为空），OSM、Google 标在井の頭恩賜公園西园那一点；高德弹了登录框挡住了标记，但地图中心在同一处。副本、脚本、截图都已删。
- **审查后改的**：候选里标出圣地；去掉测试里断言常量的几行；「地图不在三家里被拒、省了不改」单独一条测试；`MetaPart` 带 `kind`。没改的判断题：`draw_places` 的参数可以改成直接传 `Character`；`degraded` 目前只有一个键，留着映射是为了后面的票照这个格式加。
