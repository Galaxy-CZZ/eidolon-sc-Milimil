# 22: 合照

**What to build:** 动态的配图偶尔是她和一两位组合伙伴的合照：可以是自拍，也可以是别人帮她们拍的，一眼认得出是谁，外貌不串。合照里的人一定也在赞的人里。只在部署者用 NovelAI 形态的中转时才有合照，OpenAI 形态的中转从不出合照。规格见 `../spec.md`：「写一条动态」里讲允许的构图和名单规矩的两处，「配图的提示词」里讲合照、坐标、只在 NovelAI 形态的几条。来历是 `04-post-image-prototype.md`（合照实测：两人 6/6、三人 2/2）和 `11-post-image-prompt.md`。

**Blocked by:** 20, 21

**Status:** done

- [x] **什么时候允许合照**，三条都满足才允许：
  - 部署者的生图是 NovelAI 形态；
  - 她自己配齐了 `photo_tag` 和 `photo_appearance`；
  - 这条动态的圈子里至少有一位也配齐了。
  
  不满足时，「这次允许的构图」里就没有合照，她不用另外知道。
- [x] **提示词**：
  - 圈子成员那一节里，标出哪几位能进合照（配齐了外貌的）。
  - `<image>` 多一栏 `with`，写合照里的人，1–2 个 id。
  - 规则加一句：想拍成自拍，就在 `action` 里写 `selfie`；不写就是别人帮她们拍。
- [x] **请求体**：
  - 多角色提示框里，她本人和 `with` 里的每个人各一个框，每框写 `girl, <角色 tag>, <外貌>`；负面也照这个结构写。
  - centers 发 `(0,0)`，`use_coords` 发 `false`。返回的 PNG 元数据会把它记成 `true`，这不影响出图，别去「修」。在代码注释里记一句。
  - 人数 tag 只写在 base 里：
    - `action` 里有 `selfie`（合照里不剥）：写 `{n}girls, selfie`，景别收到 `portrait` 或 `upper body`；
    - 没有 `selfie`，就是别人拍：两人写 `2girls, side-by-side`，三人写 `3girls, group picture`，景别 `upper body` 或 `cowboy shot`。
  - `outfit` 全员共用。合照里放行 `holding hands`。去重用的那个固定集合，按实际人数换。
  - 人数 tag 和每个人的外貌由服务器写进去，不经过清洗。
- [x] **尺寸**：合照用 1216×832 的横图。
- [x] **降级**：选了合照，`with` 却是空的，或者有人不在可选名单里，就降成她一个人的摆拍，景别保留，记一次降级。
- [x] **名单**：合照里的人一定算进赞的人，她没写也补上。
- [x] **测试**，都看 `FakeImageService` 收到的请求体：
  - 两人、三人；自拍和别人拍；
  - 景别的范围；
  - `with` 无效时降成摆拍；
  - OpenAI 形态下、圈子里没有配齐的人、她自己没配外貌时，都不允许合照；
  - 合照里的人进了赞的人。
- [x] **验收**：在本地构建版上用假生图造一条合照动态，看时间线显示横图。要用真中转出图看效果时，先向用户报张数，等他点头再出。
- [x] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

## Comments

### 票 20 交接

- 合照的人从圈子里选：`PostMaterial.circle` 是 `Member(character, relation)` 的列表，`character.photo_tag`、`photo_appearance` 在那里。「圈子里至少一位配齐外貌才允许合照」照它判断。
- 「合照里的人必定算进赞」放进 `moment_prompt.parse_post`：现在赞是先去掉圈子外的、去重，再截到 `LIKES`/`BIRTHDAY_LIKES`（超了记 `likes_over`）。补人的时候要放在截掉之前还是之后，自己定。

### 票 21 交接

- 构图在 `photo_prompt.Composition`（现在六种）里加 `group`；`read_picture(fields, allowed)` 按 `allowed` 认构图，`_PEOPLED_FIXED` 按构图给去重的固定集合（合照要按实际人数换掉 `_FIXED` 里的 `1girl`、`solo`）。`_field(..., alone=True)` 剥 `holding hands`，合照传 `alone=False`；`_peopled`/`_no_one`/`_unaware` 是各构图另外丢掉的。
- 尺寸走 `ImagePrompt.size`（`PORTRAIT`/`LANDSCAPE`），生图客户端已按它发、按它查，合照给 `LANDSCAPE` 就行。多角色框要改 `image_generation.generation_request` 的 `char_captions`（现在写死空列表）。
- 允许的构图由 `moment_draws.draw_compositions(generating, photographed, random)` 给；合照的条件（NovelAI 形态、圈子里有配齐的人）加在这里或在 `Moments._material` 里追加，`PostMaterial.compositions` 是传给提示词和解析器的那份。
- `moment_prompt` 里「这次允许的构图」一节的说明在 `COMPOSITION_NAMES` 和 `COMPOSITIONS_CLOSING`，`with` 栏要补进去；她写的各栏原样存进 `moments.image`（JSON，`_WRITTEN` 列了哪几栏），`with` 也要加进 `_WRITTEN`。
- `COMPOSITIONS_CLOSING` 末条现在写「画面里只有你一个人，或者没有人」，加合照时要改。

### 实现说明（票 22）

- **`photo_prompt`**：`Composition` 加 `group`（七种）；`read_picture(fields, allowed, idols, pictured)` 多了 `pictured`（能进合照的人）。`with` 按 id 认，逗号、顿号、空格分隔，去重后截到 `GROUP_MOST`（2）；空的或有人不在 `pictured` 里，就按 `posed` 重读一遍，`PictureTag.alone_instead` 为真。合照的 `PictureTag` 多了 `others`（合照里的人）和 `selfie`。`_group` 用 `{n}girls`、作品 tag、质量 tag、拍法 tag、景别和圈子里各人的 `photo_tag` 去重，另外丢掉 `1girl`、`solo`、`no humans`（`_crowded`），`holding hands` 放行。`action` 里的 `selfie`（含改写来的 `group selfie`）进 base，不留在 `action` 里。选景别抽成 `_framing`，和单人构图共用。
- **`picture_prompt`**：合照的 base 是 `{n}girls, 作品 tag, 画风, selfie | side-by-side | group picture, 景别, place, outfit, action[, looking at viewer]`，后接质量 tag；`ImagePrompt.characters` 是每人一个 `girl, <tag>, <外貌>`，她排第一；负面照用 `NEGATIVE_PROMPT`；尺寸 `LANDSCAPE`。
- **`image_generation.generation_request`**：`char_captions` 照 `ImagePrompt.characters` 填，负面每人一个空串框，centers 都是 `(0,0)`，`use_coords` 还是 `false`；PNG 元数据记成 `true` 的事写在注释里。
- **`moment_draws.draw_compositions(generating, photographed, random, group)`**：`group` 是必填参数，为假时去掉合照，她没配外貌时照旧只给无人的三种。`Moments._material` 先抽圈子，再定构图，`group` = 部署者的生图是 NovelAI 形态，并且圈子里有人配齐了外貌。
- **`moment_prompt`**：「圈子成员」里能进合照的人标 `GROUP_MARK`（「（能一起合照）」），只在允许合照时标；允许合照时结尾换成 `GROUP_CLOSING`（景别范围、`with` 一栏、outfit 大家共用、画面里是你和 with 里的人）；`POST_RULES` 加了「合照想拍成自拍，就在 action 里写 selfie」；`_WRITTEN` 加了 `with`；降成摆拍记降级 `with`（`WITH`）。合照里的人在截断之前补进赞的名单，截断时只从她写的人里、从末尾截，所以合照里的人不会被截掉。
- **判断**：
  - `with` 写了超过 2 个合法的 id 时，静默截成前 2 个，不降级、不记数。
  - 合照里的人是补进去的，不记降级；她自己有没有写，在 `Post` 上看不出来（见票 29 交接）。
  - 降成摆拍以后存的 `composition` 是 `posed`，`with` 照她写的原样存。
- **验收**：用真的解析器、提示词和请求体代码，在本地库给 Sallyn 造了一条真乃和灯织的合照动态，图是假的 1216×832 PNG，经 `kept_as_webp` 转换。请求体和调研 4.2 的草案一致。本地构建版上宽屏和手机的缩略图都是 160×109，放大后是横图，赞里补上了灯织。验完删掉了数据和脚本。
- **真中转出图**（用户同意，4 张）：走同一套代码，出了两人别人拍（真乃、灯织）、三人别人拍（真乃、灯织、めぐる）、两人自拍（甘奈、甜花）、三人自拍（めぐる、真乃、灯织）。4 张人数都对，都认得出是谁，外貌没串，自拍没有多出手或手机。`outfit` 写在 base 里大家共用，但模型不一定给每个人都穿上：灯织两次带着校服领带，`scarf`、`waving` 也只落在一个人身上。不影响认人，照规格没改。
- **审查里没改的**：`"group"` 字面量散在 `draw_compositions`、`post_prompt`、`read_picture`、`picture_prompt` 几处，没收成常量；`Moments._material` 里自己拼「能不能合照」的条件，直接和 `"novelai"` 比较，没挪到 `ImageSettings` 上。这两处都是判断题。
