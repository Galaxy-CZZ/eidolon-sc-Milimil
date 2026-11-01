# 15: 地点池的格式、校验和圣地

**What to build:** 维护者手里有一份地点池数据文件，后端启动时读入、校验，写错了起不来，并说清楚错在哪。这一张先收圣地和演出场馆，同时给每位偶像标上偏好的地点类别、给工作标上会去哪类地方，生成一份能逐条点开地图的 HTML 交给用户校对。地点在动态里怎么用由 17 接上，其余各类由 16 补到约 400 个。规格见 `../spec.md`「数据文件：地点池、工作的地点、偶像的喜好」；来历是「拍板：地点池怎么整理」（`10-place-pool-curation.md`）和调研 `research/moments-place-pool` 分支上的 `.scratch/moments/research/place-pool.md`（第 1.4 节是圣地样例，第 3 节是扩充来源，第 6 节是数据文件的形状）。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] **格式**：新数据文件 `characters/places.toml`，写法照 `jobs.toml`。
  - 开头注释写字段说明，以及「Contains data © OpenStreetMap contributors, ODbL」。
  - 每个地点的字段：`id`、`name`（日文原名）、`area`（区市町村）、`lat`、`lon`、`category`、`note`（一句中文）。
  - 可选字段：`idols`、`source`（卡面名加考据链接）、`seasons`、`slots`。
  - 还有 `checked`（核对日期）。
  - 不加给生图用的 tag 字段。
- [x] **类别**：14 类，标识用英文，在代码里写死。每类在室内还是室外，照规格那张表。
  - `seasons` 取春夏秋冬：东京的 3–5 月是春，6–8 月是夏，9–11 月是秋，12–2 月是冬。
  - `slots` 取工作的三段：上午、下午、晚上。
- [x] **校验**：启动时读入；写错了后端起不来，并说清楚是哪一条、哪个字段错了。要查的有：
  - id 重复。
  - 类别不认识。
  - 坐标出了东京加近郊的大致范围。
  - `idols` 里有不是角色的。
  - `seasons`、`slots` 写了不认识的值。
  - `checked` 不是日期。
- [x] **`jobs.toml` 加可选字段 `places`**：一个类别列表，照规格那份对照写上，写了不认识的类别就起不来。练习室、事务所、摄影棚、录音棚、医院、见面会这类不写。
  - 「一日游」去的是近郊，不限类别，所以 `places` 里除了类别还可以写 `nearby`，意思是任何一类、但只挑东京都以外的地点。规格只说了「只挑 `area` 在近郊的」，具体判断由这张票定：东京都以外地点的 `area` 带上县名（比如「神奈川県鎌倉市」），带县名的只能是神奈川、千葉、埼玉。
- [x] **`characters.toml` 加 `place_likes`**：每位偶像 2–4 个偏好类别，写错就起不来。不像 `liked_gifts` 那样要剧情出处。
- [x] **圣地**：40–60 处，从调研的 20 个样例开始扩充。
  - 只收有对照照片、能复核的考据；动画版的圣地、已经拆掉或关门的不收。
  - 每处照实际的地点归类，带上 `source` 和 `idols`。
  - 坐标取自来源（OSM、Wikidata、官方页面），不让模型估。
  - 角色资料里写明的地方，也带上 `idols`。
- [x] **演出场馆**：`world.json` 里在范围内（东京都加一日游的近郊）的 live 场馆全部收进来，名字和演出的 `venue` 对得上。
- [x] **README 的「致谢」**（三种语言）加一行 OpenStreetMap 贡献者（ODbL）。界面上不加。
- [x] **人工**：在 `E:/tmp/` 生成一份 HTML 交给用户校对：
  - 逐条列出地名、区、类别、说明、有关的偶像、出处，每条都能点开地图。
  - 同一份里还要有 28 位的 `place_likes`，以及工作的 `places` 对照。
  - 用户校对完，把结果写进数据文件。
- [x] **测试**，照 `test_job_list.py`：
  - 仓库里的那份能读入。
  - 写错的各种情形都让后端起不来，并说清楚是哪里错。
  - 每个演出场馆都对得上 `world.json` 里的场馆：这一条放在测试里，不放在启动校验里，免得同步 `world.json` 后起不来。
  - 28 位都有 `place_likes`。
- [x] 下载的抽取文件、中间数据不进仓库。推送前扫一遍有没有密钥和大文件。
- [ ] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

## Comments

### 实现说明（票 15）

- **新模块 `place_pool.py`**：`load_place_pool(path, characters)` 读 `characters/places.toml`，返回 `Place` 列表，按文件里的顺序。
  - 写错了抛 `PlacePoolError`（RuntimeError），报出是哪个地点、哪个字段。
  - 另有 `check_job_places(jobs)`、`check_place_likes(characters)`。
  - 三个都在 `assembly.build` 里、工作清单读完以后调。地点池现在只校验，不往下传，17 接上时再存进 `Backend`。
- **写死在代码里的**：
  - `Category`（14 类英文标识）、`INDOOR`（室内 6 类，照规格那张表）。
  - `Season`（spring/summer/autumn/winter）；`slots` 直接用 `job_list.Slot`。
  - `NEARBY = "nearby"`、`NEARBY_PREFECTURES`。
  - 坐标范围：纬度 35.1–36.1，经度 138.9–140.3（东京都去掉岛屿，加近郊）。
- **近郊怎么判断（这张票定的）**：东京都以外的地点，`area` 以县名开头，只能是神奈川県、千葉県、埼玉県。`Place.nearby` 就看这个前缀。`area` 开头是别的府县（含北海道）时起不来；府中市不算，因为「府」字前面没有字。
  - 校验管不到的：坐标在东京都外、`area` 却漏写县名的地点。光靠矩形范围分不出都界，靠维护者照规则写。
- **加了票里没列的可选字段 `venues`**，只给演出场馆用。
  - 原因：`world.json` 里同一个场馆有几种写法（「パシフィコ横浜 国立大ホール」和「パシフィコ横浜国立大ホール」，幕張メッセ也有两种）；还有和显示名不一样的（「TACHIKAWA STAGE GARDEN(立川ステージガーデン)」）。
  - `Place.venue_names` 返回演出里的写法：写了 `venues` 就是它，没写就是 `name`。不是场馆的地点返回空。
  - 京王アリーナTOKYO 和武蔵野の森総合スポーツプラザ是同一处（Wikidata Q21019690），合成一条。
- **`checked` 写成 TOML 的日期**（`checked = 2026-10-31`），不是字符串。
- **`ListedJob.places`**：`tuple[str, ...] | None`。
  - 「做喜欢的事」（hobby）列出了全部 13 类（不含演出场馆），没另造一个表示「不限」的值。
  - `nearby` 只用在「一日游」。
  - 工作的 `places` 和偶像的 `place_likes` 都不能写 `venue`，因为演出场馆只给她往年今天的演出用。
- **`Character.place_likes`**：`tuple[str, ...] | None`，没写是 None。
  - 写了就必须 2–4 个，`[]` 也算写错。
  - 启动时不要求每位偶像都写（はづき不是偶像）。28 位都有，由测试 `test_every_idol_likes_two_to_four_kinds_of_place` 守着。
- **数据**：一共 56 处，圣地 40、演出场馆 16。
  - 场馆：`world.json` 里在范围内的全收了。盛運輸アリーナ在青森，不收；线上的 ASOBISTAGE 也不收。
  - 圣地：子代理按调研的 1.2 节读考据文章，又从すゞや的 Google My Maps 导出里找有对照照片的点。不够 40 处，加了三个表外来源：赤イカ缶的 note、気ままにダンス。、月奏。只靠这三个来源进来的有 8 处。
  - 太细、归不了类的点，换成了所在的地点（站前一带并进京王聖蹟桜ヶ丘SC，渋谷的十字路口并进センター街，府中四谷橋换成西府緑地）。
  - 坐标都取自 Wikidata P625 或 OSM 的具体要素，抽查 8 条都和来源一致。
  - 只来自［背景］的 6 处没有 `idols`，测试放过了 `source` 以「［」开头的。
  - 角色资料里没有写明具体的东京地点，所以 `idols` 只来自圣地考据。
  - 偶像覆盖不均：美琴、愛依、ルカ、羽那、はるき没有圣地，にちか只有一处。
- **用户 2026-10-31 校对过，照校对页定稿**，以下几条都照现状收：表外来源、并成所在地点的几条、考据者自己说是推定的几条、存续有风险的几条、6 处只有背景的、アトレ秋葉原1、明治神宮外苑只写秋。
- **测试 `test_place_pool.py`**：
  - 仓库那份能读入，圣地在 40–60 之间，场馆至少 10 个。
  - 每个场馆的 `venue_names` 都在 `world.json` 的场馆里。这条放在测试里，不放在启动校验里。
  - 28 位都有 `place_likes`。
  - 写错的各种情形都让后端起不来。
  - conftest 的 `CharacterConfig` 默认拷一份仓库的 `places.toml`，去掉 `idols` 行（照 bar_visits 去掉 `not_for` 的先例）；`add()` 加了 `place_likes` 参数。
- **README 的致谢**（三种语言）：加了一行 OpenStreetMap 贡献者（ODbL），连同 Wikidata（CC0，不要求署名，写上无害）。
- **审查后**：
  - `place_likes = []` 改成也起不来。
  - 测试里走同一分支的重复参数删掉了。
  - 辅助函数改了名。
  - 没改的判断题：加载函数和 `job_list`、`gift_catalog` 写法几乎一样，没抽共用函数（仓库现成的写法）；类别存成字符串、没用 `Category` 类型（避开 `job_list` 和 `place_pool` 的循环导入）。
