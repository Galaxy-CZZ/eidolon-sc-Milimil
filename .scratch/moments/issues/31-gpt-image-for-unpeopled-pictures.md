# 31: 无人配图用 GPT Image 出图，失败降级到 NovelAI

**What to build:** 她发朋友圈时，风景、食物、物品这三种无人构图的配图，在部署者另配了 OpenAI 图像格式的服务（GPT Image 系列）时交给它出：GPT Image 认得真实的地点和日文招牌，比 NovelAI 用 tag 画的「日本的某条街」更像她真去了那家店。GPT Image 失败就改用 NovelAI 照现在的样子出，NovelAI 也失败就发纯文字。对话里的照片、朋友圈里有人的构图（自拍、他拍、抓拍、合照）都不变。

这张票推翻了朋友圈规格 Out of Scope 里的「无人构图换用 GPT Image 系列生图：NovelAI 实测够用」。决定来自 2026-11-01 和用户的两轮拷问，原型图和提示词在 `E:\tmp\gpt-image-proto\`（收尾时推到 origin 的 `prototype/moments-gpt-image`）。

**Blocked by:** none

**Status:** done

**分支：** `feat/moments-gpt-image`（从 main 开），PR 直接进 main。

## 先读

- `docs/agents/implementing.md`（测试、draft PR、收尾），`docs/agents/local-acceptance.md`（本地验收）。
- 朋友圈规格 `../spec.md` 的「配图」各节（七种构图、无人构图的前缀、尺寸按构图定、清洗），票 `21-post-images.md`、`22-group-photos.md`。
- 生图现在的样子：`backend/src/eidolon/image_generation.py`（NovelAI 格式和「OpenAI 图像格式」两条路；注意现有的 OpenAI 图像格式是给转发 NovelAI 的中转用的，发的是 tag 串、带 `negative_prompt` 和 `response_format`，**不能**拿来接 GPT Image）、`photos.py`（`Photos.picture`、排队 `_turn_on`）、`photo_prompt.py`（`ImagePrompt`、`picture_prompt`、无人构图前缀）、`moments.py`（`_picture`、`PICTURE_TIME_LIMIT`）、`moment_prompt.py`（`Picture`、`note`、`Post.degraded`）、`config.py`（`ImageSettings`、`ProxiedService`）、`proxy.py`、`prices.py`、`activity.py`。
- 后台生图页、代理页的前端，和它们的后台接口（按 `NOVELAI_*`、`image` 这些名字 grep）。前端规矩见 `frontend/AGENTS.md`，界面文案要少。

## 定下的做法

### 范围
- [x] 只有朋友圈的风景、食物、物品三种构图走 GPT Image。对话照片、有人的构图、合照不变。
- [x] 只用部署者的 key，不做用户自带的 GPT key。
- [x] GPT Image 是 NovelAI 生图之外的附加服务：没配部署者的生图（`image_settings` 为 None）时它不生效，朋友圈照旧全发纯文字；`draw_compositions` 的规则不变。

### 配置
- [x] 新的一组设置（建议叫 `SceneryImageSettings` 一类，名字自定，进 `GLOSSARY.md`）：地址（到 `/v1`，默认 `https://api.openai.com/v1`）、key、模型 ID（默认 `gpt-image-2`）、质量（`low`/`medium`/`high`/`auto`，默认 `medium`；2.5 系列的 `xhigh`/`max` 也放行或者留作自由文本，自己判断，写进实现说明）、风格句（默认见下）。key 留空就是不启用。
- [x] 环境变量 `GPT_IMAGE_API_KEY`、`GPT_IMAGE_BASE_URL`、`GPT_IMAGE_MODEL`、`GPT_IMAGE_QUALITY`、`GPT_IMAGE_STYLE`；后台设定覆盖环境变量（ADR-0013），照现有生图设置的做法接进实时配置。
- [x] 后台「生图」页加这一组，带「试一张」：照 `try_image_service` 的做法出一张固定内容的风景，不计费、不记录。
- [x] 网络代理加一个单独的开关 `gpt_image`（`ProxiedService`、`EIDOLON_PROXY_SERVICES`、后台代理页），默认不勾，和 `image` 分开：部署机连 `api.openai.com` 要走代理，而 NovelAI 中转可能直连。

### 请求
- [x] `POST {地址}/images/generations`，Bearer key，JSON 只发 `model`、`prompt`、`size`、`quality`、`n: 1`。不发 `negative_prompt`、`response_format`。
- [x] 返回 `data[0].b64_json`（带不带 `data:` 前缀都行）或 `data[0].url`（同一个客户端下载）都接；复用 `image_generation.py` 里现成的解码。
- [x] 超时、HTTP 错误、返回解析不了的，照 `ImageFailed` 的三种原因归类。

### 尺寸
- [x] 直接请求目标尺寸：风景 `1216x832`，食物、物品 `832x1216`（gpt-image-2 起支持自定义尺寸：宽高是 16 的倍数，总像素至少 655,360）。
- [x] 返回的尺寸正好对：原样保存（照旧转 WebP、去元数据），不裁也不缩放。
- [x] 尺寸不对（codex 反代实测总回 1448×1086，竖图请求还回过近方图和反方向的图）：按目标比例居中裁剪，再缩放到目标尺寸。横竖反了也照裁，不算失败。现在 `kept_as_webp` 对尺寸不对的一律报 `bad_image`，NovelAI 那条路保持不变。
- [x] 文档写明需要 gpt-image-2 或更新的模型（更早的只认预设尺寸，会被 400 拒，每次都降级）。

### 提示词
服务器拼，模型不多写一栏。顺序和措辞照加测时验证过的（`E:\tmp\gpt-image-proto\` 的 R1 四张）：

```
{风格句}
Subject: {scenery | food | an object}, a casual snapshot a young woman living in Tokyo just posted to her social media feed. {人}
Place (background information only; do not add things because of it): {地点原名}, {area}, Tokyo — {地点 note}
What the picture shows (follow this): {她写的 note}
Details: {清洗后的 place/action 栏 tag，逗号分隔}
When: {月份英文}, {morning | afternoon | evening | night 之类的时段}, {天气}.
{视角句} No added text, captions or watermarks.
```

- [x] `{人}`：风景是 `At most a few small, distant passersby; no one is the subject.`；食物、物品是 `No people in the frame.`
- [x] 没有地点（在家、宿舍、写了 none）时整行 `Place` 省掉。`area` 里已经带县名的（神奈川、千葉、埼玉）不要再写 `Tokyo`。
- [x] 天气用发动态时东京的天气（`weather`，拿不到就省掉）；时段按东京时间算。
- [x] 视角句：风景 `Seen at eye level from the ground, as if she took it herself.`；食物、物品 `Seen from close by, as if she took it herself.`（措辞可微调）。
- [x] 她写的 `note` 原来「不发给生图服务」，现在发：规格里那句要改（见文档）。
- [x] 默认风格句（写法丙，用户定的）：

  > Flat cel-shaded anime background art, like a background painting from a TV anime: clean line art, cel shading, simplified shapes and details, soft flat colors. It must look hand-drawn, never photographic: no lens effects, no HDR, no photo-real textures.

- [x] 拼提示词是纯函数，喂素材（构图、地点、note、tag、时间、天气、风格句），线上和评测命令走同一个。

### 排队和降级
- [x] GPT Image 单独排队，并发固定 1，不占 NovelAI 的名额，也不排在对话照片后面。
- [x] 一张图给 GPT Image 最多 4 分钟（含排队）。超时、报错、返回的不是图、被审核拦下：马上改用 NovelAI，照现在的 tag 提示词、现在的队列，用 `PICTURE_TIME_LIMIT`（10 分钟）里剩下的时间。NovelAI 也失败，照现在发纯文字，动态照发、记成功。
- [x] 降级时这条动态的 `degraded` 记 `picture_fallback: 1`（只记次数，不记内容），和现有的降级计数一样进运行记录。

### 计费和记录
- [x] 按张计费（`billing` 的 `images`）：返回了图就记 1 张，报错、超时记 0，和 NovelAI 一样。
- [x] 服务调用记它自己的地址和模型（`activity.host`、model），看板上自然分成单独一行。降级时 GPT 和 NovelAI 两次调用都记，GPT 那次记失败原因。
- [x] `prices.py` 的 `PRESETS` 只加 `("api.openai.com", "gpt-image-2", "images")`，按 medium、1216×832 左右一张的价钱（从 OpenAI 价格页查，注明日期和质量）；中转和其他质量档没有预设，管理员在后台填。

### 评测
- [x] `eidolon eval moments` 的 HTML 里，无人构图除了清洗后的 tag 串，再显示一份拼好的 GPT 提示词。不真的生图。场景里没有天气、地点的，照缺省省掉。

### 文档和条款
- [x] 隐私政策（`frontend/src/i18n/zh.ts` 的「生图服务」一条）照实改：她发无人配图时，会把她写的一句配图说明、地点、时段和东京天气发给部署者配置的 OpenAI 图像格式服务（配了的话）；其余照旧。文案要少。
- [x] `GLOSSARY.md`「生图」条补上无人配图的服务。
- [x] 朋友圈规格 `../spec.md`：Out of Scope 里那条改成「已做，见票 31」；「配图」里 `note` 不发给生图服务那句、无人构图那几句补上 GPT Image 的走法。
- [x] `docs/configuration.md`、`docs/configuration.ja.md`、`docs/configuration.en.md`、`.env.example`、`docs/agents/deploying.md` 加新的环境变量和代理开关，写明最低 gpt-image-2、中转返回尺寸不对时会裁剪。
- [x] 不写 ADR。

## 测试

照现有先例写，走公开接口：`test_image_service.py`（请求体、解码、尺寸）、`test_moment_*`（配图、降级、运行记录；`FakeImageService` 要能区分两个服务、分别给成功和失败）、`test_live_config.py`（后台覆盖）、`test_proxy.py`（新开关）、`test_moment_eval.py`（HTML 里的提示词）、`test_activity_records.py`、价格相关测试；前端 `adminConfig.test.ts` 一类。

要覆盖：
- 请求体只有那五个字段、走 `/images/generations`。
- 尺寸对就原样、不对就裁剪缩放（含横竖反了的）。
- 提示词：三种构图、没地点、area 带县名、没天气。
- 只有无人构图走 GPT；有人的构图、对话照片不走。
- GPT 失败、超时、4 分钟到点都降级到 NovelAI，记 `picture_fallback`；两边都失败发纯文字。
- 没配 NovelAI 时 GPT 不生效。
- 两个服务的队列互不占名额。
- 「试一张」。

## 验收

- [x] 本地构建版（`docs/agents/local-acceptance.md`）上：后台配上 GPT Image（用 MCP 那边的 codex 反代或任何能用的 OpenAI 格式地址；没有能用的 key 就用一个本地假服务验接口通路，在实现说明里写明）点「试一张」出图；造一条到点的无人配图动态，看到配图、运行记录里的服务调用；把 GPT 地址改坏，看到降级到 NovelAI、`picture_fallback` 计数。截图留给用户看画风。
- [x] 能用接口和测试验的自己验，只把「图好不好看」留给用户。

## Comments

### 实现说明（票 31）

**改了哪些模块和接口**

- `config.py`：新增 `GptImageSettings`（`api_key`、`base_url`、`model`、`quality`、`style`），从 `GPT_IMAGE_*` 读，挂在 `Settings.gpt_image` 上。`ProxiedService` 加了 `gpt_image`，排在 `image` 后面。`gpt_image_style_from_env()` 给评测命令用，没配 key 也能读到风格句。
- 新模块 `gpt_image_prompt.py`：纯函数 `gpt_picture_prompt(tag, note, place, at, weather, style) -> GptPrompt(text, size)`。线上（`moments`）、「试一张」和评测命令用的都是它。
- `image_generation.py`：
  - 新增 `GptImageGenerator`，请求体由 `gpt_image_request` 拼，只发五个字段。
  - OpenAI 图像格式的返回解析抽成了 `_openai_picture` / `_openai_item`，两条 OpenAI 路共用。
  - `kept_as_webp(..., fit=True)` 用来居中裁剪再缩放，NovelAI 那条路照旧不带 `fit`。
  - 新增 `try_gpt_image`，`GPT_TIME_LIMIT = 240`。
- `live_config.py`：
  - 新的一项 `gpt_image`（`_GptImage`），保存前用 `try_gpt_image` 试调。
  - `LiveConfig.gpt_image_settings`、`gpt_image_style`、`gpt_image_generator()`。生成器只在部署者也配了生图时才返回，否则是 None。
  - 代理的连通检查（`_proxy_targets`）里加了 `gpt_image`。
- `admin_config_api.py`：新增 `GptImageInput`，`ProxyInput.gpt_image`。
- `assembly.py`：新增 `gpt_image_transport`，测试用。
- `photos.py`：
  - `Photos(…, gpt=)`，新增 `gpt_on`、`gpt_picture(prompt, until, stripped)`。
  - 队列按 (`image` | `gpt_image`, key, 并发数) 分开排。GPT Image 的并发固定 1，也不排在照片后面。
  - `picture()` 多了 `stripped` 参数，见下面的判断。
- `moments.py`：`_picture` 对无人构图先走 GPT Image，限时取 4 分钟和 10 分钟剩余里较早到的那个。超时、报错、返回的不是图都会降级到 NovelAI，用 10 分钟里剩下的时间；降级时在 `degraded` 里记 `picture_fallback: 1`（常量 `moment_prompt.PICTURE_FALLBACK`）。
- `activity.image_origin` 同时接受两种设置，所以 GPT Image 的调用记成 `image` 服务，带它自己的 host 和 model。
- `prices.PRESETS` 加了 `("api.openai.com", "gpt-image-2", "images")`。
- `moment_eval.py`：`PostCase` 多了 `at` 和 `weather`，`PostRun` 多了 `gpt`。HTML 里在 tag 串下面多显示一段「GPT Image 提示词 · 宽×高」。`evaluate(gpt_style=)`。
- 前端：
  - `adminConfig.ts`：「生图」标签下加了 `gpt_image` 卡（`GPT_IMAGE_QUALITIES`），代理开关也加了一个。
  - `zh.ts`：卡片标题和说明、「质量」「风格句」两个字段名、代理开关的名字，以及隐私政策的「生图服务」一条。
- 文档：
  - `GLOSSARY.md` 原来没有「生图」这一条，这次新加了，写明无人配图服务（GPT Image）。顺手把「配图」「网络代理」两条也补上了。
  - 规格 `../spec.md`：改了 `note` 那句，补了一条「无人构图走 GPT Image」，Out of Scope 改成「已做，见票 31」。
  - 三份配置指南：「朋友圈」一节加一段，代理表加一行。
  - `.env.example`、`docs/agents/deploying.md` 都改了。

**做了哪些判断**

- **命名**：设置、后台项、环境变量、代理开关一律叫 GPT Image（`GptImageSettings`、`gpt_image`、`GPT_IMAGE_*`），四处叫法一致。没用 `SceneryImageSettings`，因为 scenery 是七种构图里的一种，容易看混。
- **质量**：用固定列表 `low`、`medium`、`high`、`auto`、`xhigh`、`max`，没留自由文本。OpenAI 图像生成指南（2026-11-01 查）确认 2.5 系列多出 `xhigh` 和 `max`。填了列表以外的值，启动时报错，后台回 422。gpt-image-2 不认的档位，「试一张」会拦下来。
- **风格句**：清空就用默认那句，不允许「不要风格句」。原因是没有这一句，出来的图会偏照片。
- **「试一张」**：就是这张卡保存时的试调，和「生图」卡一样，按钮还是「试调并保存」，没另加按钮（界面文案要少）。试的内容固定：一条傍晚的商店街，11 月、17 点、晴，地点留空。
- **时段**：按东京时间分六档。0–4 点 late at night，5–10 点 morning，11–13 点 midday，14–16 点 afternoon，17–18 点 evening，19–23 点 night。比票里列的多了 midday 和 late at night 两档。
- **天气用词**：clear、cloudy、overcast、foggy、rainy、snowy、thunderstorm。
- **提示词里的可省项**：note 是空的就省掉那一行；没有 tag 就省掉 Details 一行。tag 按 place 在前、action 在后排，去重。`Place.nearby`（神奈川、千叶、埼玉）的地点不加 `Tokyo`。
- **剥掉的 tag 只记一次**：GPT Image 的调用记下剥掉的 tag。降级时，如果 GPT 的请求已经发出去了（抛的是 `ImageFailed`），NovelAI 那次就不再记，免得在看板上算两遍。如果是在 GPT 的队列里就超时了、请求根本没发，就照旧记在 NovelAI 那次上。
- **服务状态**：GPT Image 的调用也算在「生图」服务里。看板的「按模型」那张表里它单独一行，但用户看到的「照片」状态会把两边合在一起算。没另加一项服务状态。
- **价格**：取 OpenAI 图像生成指南成本表里 GPT Image 2 medium 横竖图（1536×1024、1024×1536）的 $0.041。表里没有 1216×832 这一档，提示词的文字 token（每百万 $5）也没算进去。
- **doctor**：不试 GPT Image，每张都要花钱，和生图一样。部署文档里写了：要不要走代理由部署者自己加 `gpt_image`。

**验收**

- 本机 `.env` 里没有能用的 OpenAI 格式生图 key，所以起了一个本地假服务，只验接口通路：
  - 假服务是 `E:/tmp/eidolon-31/fake_image.py`，不在仓库里。
  - OpenAI 格式那边按 codex 反代的样子，横图一律回原型里真的 GPT 出图（`R1-S1-a.png`，1448×1086），竖图回 `S6-anime.png`。
  - NovelAI 格式那边回 ZIP。这次起后端时用环境变量把 `NOVELAI_BASE_URL` 指到假服务，`.env` 没改。
  - 一张付费图都没花。真服务出图留给用户。
- 本地构建版上：
  - 用 Playwright 在后台「生图」标签填了 GPT Image 卡，点「试调并保存」，假服务收到一张风景的请求，五个字段都对，卡片显示「已被后台覆盖」。
  - 塞了一条到点的计划（真乃，真实的对话模型）：
    - 她写了物品构图，走了 GPT Image，配图正常显示。提示词里有蔵前的地名和介绍、她写的 note、tag，以及「November, evening, clear」（东京 18 点、真实天气）。返回的尺寸不对，裁成了 832×1216。
    - 写成摆拍的那条直接走了 NovelAI。
    - 让假服务回 503 以后，又一条物品构图降级到了 NovelAI：运行记录里有 `{"picture_fallback": 1}`，GPT 那次调用记成 `server_error`、计 0 张，NovelAI 那次成功。
  - 看板「花费」的「按模型」表里，`gpt-image-2` 和 `nai-diffusion-5-curated` 各占一行。
- 截图在 `E:/tmp/eidolon-31/screens/`，图是原型里的旧图，不代表真服务的画风。
- 验完把后台的两项覆盖都恢复成 .env 的值。为了让 Sallyn 算活跃，验收时开过一个对话，这个对话和这次造的 5 条动态、当天的计划都从本地库删掉了。运行记录留着。

**审查**

- 照审查意见改了：
  - 删掉和合并了重复的测试：常量价格、pydantic 的 422、和别处重复的尺寸拒绝、裁剪的参数化、401/400 两行、食物和物品两份。
  - `gpt_image_origin` 并进了 `image_origin`；去掉了 `fitted_as_webp`。
  - 队列的服务名改成类型化的 `QueuedService`；评测命令的风格句改用 `gpt_image_style_from_env`。
  - GLOSSARY 补了「生图」条，「网络代理」条也改了。
  - 隐私政策那句前后矛盾，改了。
- 判断题，没改：`place, at, weather` 三个参数总一起出现，可以合成一个类型（Data Clumps）。现在只在两个调用点用，就没合。

**原型**：`E:/tmp/gpt-image-proto/` 里的东西已经推到 origin 的 `prototype/moments-gpt-image`，放在 `.scratch/moments/prototype/gpt-image/`，图转成了 WebP。本地没有建这个分支。

**留给用户**

- 用真服务验一次：在后台配上 GPT Image 的地址和 key，点「试调并保存」（1 张），再等一条无人配图的动态（1 张），看画风和地点像不像。
- 用中转时，在后台给它填单价。
