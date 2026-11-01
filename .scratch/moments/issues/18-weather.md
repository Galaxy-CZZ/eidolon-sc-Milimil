# 18: 天气

**What to build:** 每条动态的 Meta 一行最后多一个天气：图标加整数气温，比如「☀ 18°」。天气取的是发的那一刻东京的值，之后不变；取不到就不显示，她也不提。她写动态时知道这会儿的天气；下雨、下雪、打雷时，地点候选只给室内的类别。规格见 `../spec.md`「天气」，以及「写一条动态」里讲天气、地点候选的两处；来历是「调研：动态旁边的天气从哪取」（`02-weather-research.md`），全文在 `research/moments-weather` 分支。

**Blocked by:** 14, 17

**Status:** done

- [x] **客户端**：
  - Open-Meteo，免 key。取一个固定东京坐标的逐小时 WMO 天气码和气温，用的是气象庁 MSM。
  - 写法照价格目录：`trust_env=False`，不进网络代理选项，不进服务状态，也不算运行记录里的服务调用。
  - assembly 能注入它的 transport，测试里换成一个新加的假天气服务：记下每次请求，能答成功，也能答失败。
- [x] **取值和缓存**：
  - 生成动态时，取「露出那一刻」所在小时的值，和动态一起存下，之后不改。
  - 内存缓存按「坐标格 × 小时」存，3 小时有效。
  - 请求失败后 10 分钟内不再请求。
  - 避开整点请求。
- [x] **7 档**：
  - 晴（0–1）、多云（2）、阴（3）、雾（45、48）、雨（51–67、80–82）、雪（71–77、85–86）、雷（95–99）。
  - 雨、雪、雷算有降水。
  - 码不在这些范围里时当作取不到。
- [x] **提示词**：「朋友圈」场合的此刻里加一行天气，写档位和气温；取不到就不给。只在写动态时加，回评论时不加。
- [x] **有降水时的地点**：地点候选只给室内的类别。室内室外照 15 写死的那张表。
- [x] **时间线接口**：天气给出 7 档之一和整数气温，没有就为空。
- [x] **前端**：Meta 一行写成「时间 · 地名 · 天气图标加整数气温」，缺哪部分就连同分隔点一起省掉。每档选一个 Lucide 图标。`moments.test.ts` 测 7 档各对哪个图标，以及省掉的几种情形。
- [x] **README 的「致谢」**（三种语言）加一行：Open-Meteo（CC BY 4.0）。界面上不加。备选服务 MET Norway 只在代码注释里记一句，不做。
- [x] **测试**：
  - 取到时：提示词里有天气这一行，时间线上有天气；7 档归类正确。
  - 有降水时，候选只有室内的类别。
  - 取不到时（请求失败、码不认识），提示词和时间线都没有天气，动态照发。
  - 3 小时内不重复请求；失败后 10 分钟内不再请求。
  - 存下的天气之后不变。
- [x] **验收**：在本地构建版上造一条带天气的动态，用 Playwright 看 Meta 一行。再在断网（或请求失败）时造一条，确认没有天气、动态照发。
- [x] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

## Comments

### 票 14 交接

- 本地验收时真模型在没给天气的情况下写了「今日は少し涼しいですね」。规格说取不到天气时「她也不提」，`moment_prompt.POST_RULES` 现在没有这条；加天气时顺手补一句（没给天气就别写天气、冷热）。

### 票 17 交接

- 下雨下雪只给室内类别：在 `moment_draws.draw_places` 里加，室内类别是 `place_pool.INDOOR`。演出场馆（`venue`）本来就算室内。

### 实现说明（票 18）

- **客户端**：新模块 `weather.py`。`Weathers(clock, transport)` 用 `httpx.AsyncClient(trust_env=False)` 直连 Open-Meteo，不走网络代理，不进服务状态，取天气在运行记录 `begin` 之前，所以不算服务调用。请求参数：`latitude=35.6895`、`longitude=139.6917`（都厅）、`hourly=weather_code,temperature_2m`、`models=jma_msm`、`timeformat=unixtime`、`start_hour`/`end_hour`（GMT）。MET Norway 只在模块注释里提了一句。`assembly.build` 新增 `weather_transport`，`Moments` 的 `weathers` 改为必填。测试用 `fakes.FakeWeather`：记下每次请求的 query，按请求的小时段回答 `code`/`temperature`，也能答 503。`make_client` 默认用一个总是失败的 `FakeWeather`，所以别的测试里的动态都不带天气。
- **取值和缓存**：`Weathers.at(when)` 取 `when` 所在小时的值。每次请求顺带取后面 `AHEAD=12` 小时，全部按「坐标格（两位小数）× 小时」放进缓存，保留 `KEPT=3h`。请求失败后 `RETRY_AFTER=10min` 内不再请求。返回里缺那一小时，就当取不到，照样缓存。`Moments._post` 在调模型前取一次，跟动态一起存进 `weather`、`temperature` 两列（表结构票 14 已经建好）。
- **7 档**：`Kind`、`KINDS`（码段）、`Weather.wet`（雨、雪、雷）。码不在这些范围里、码是 null、气温不是数字，都当取不到。
- **提示词**：`HerNow.lines(..., weather)` → `producer.posting_now_prompt(..., weather)`，在此刻的时间那一行后面加 `weather_line`：「东京这会儿的天气：多云，19°C。」。只有发动态时传天气。`POST_RULES` 补了票 14 交接的那条：「此刻」里没写天气时，正文别提天气和冷热。
- **地点**：`draw_places(..., roofed=)`，有降水时只挑 `place_pool.INDOOR` 里的类别。
- **接口和前端**：时间线的 `weather` 字段是 `{"kind", "temperature"}` 或 null。`lib/moments.metaParts` 多了一段 `weather`，带图标、读屏标签和「18°」。图标：晴 `Sun`、多云 `CloudSun`、阴 `Cloud`、雾 `CloudFog`、雨 `CloudRain`、雪 `CloudSnow`、雷 `CloudLightning`。DESIGN.md「朋友圈页」改了这一行的写法。README 三种语言的致谢各加一行 Open-Meteo（CC BY 4.0）。
- **判断**：
  - 「避开整点」的做法：每小时前 `PEAK=2min` 内，缓存里没有新鲜值就不请求，这条当作取不到，不让后台循环等。代价是约 3% 发在整点后两分钟内、且缓存过期的动态没有天气。
  - 雷那一档在提示词和读屏里写「雷雨」，规格写的是「雷」，中文单写一个「雷」不自然。
  - 天气按调模型前那一刻取，写下的时间是调完模型以后。跨整点时差一小时，可以忽略。
- **验收**：真接口取到东京「晴 22°」。在本地库副本上用真对话模型发了两条：一条带天气，构建版 Playwright 看到 Meta 一行「刚刚 · ☀ 22°」，图标的读屏名是「晴」；另一条天气请求失败（transport 回 503），没有天气，照常发出，正文没提天气，Meta 一行是「刚刚 · 隅田川テラス」。副本、脚本、截图都已删。
- **审查后改的**：去掉断言常量的测试，精简不分支的参数；缓存条目换成小 dataclass；时间线读档位改用 `ALL_KINDS`，不再借用文案表；天气以 `Weather` 往下传，到 `producer` 里再拼成一行；`Moments.weathers` 改为必填；返回里缺那一小时也缓存；图标对齐改用 `align-middle`；`WEATHER_ICONS` 不再导出。没改：`moments.test.ts` 里 7 档逐一对图标那组照票保留，「晴」那一行和完整断言那条有重复。

