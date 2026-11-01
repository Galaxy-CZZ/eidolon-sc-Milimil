# 21: 配图（单人和无人的六种）

**What to build:** 大约三分之二的动态带一张配图，有六种：风景、食物、物品、自拍、别人帮她拍的摆拍、走路时被抓拍。画风和照片一样是部署者设的，全年龄；画面里从不出现制作人。时间线上是一张窄的缩略图，点开能放大。配图失败或者超时了，动态照样发成纯文字。用户在回合里要的照片会插到等着的配图前面，所以朋友圈不拖慢照片。合照由 22 接上。规格见 `../spec.md`：「写一条动态」里讲带不带图、允许的构图、`<image>` 的栏和写坏了的几处；「配图的提示词」全节（合照那条除外）；「存储」「接口」「前端」里讲配图的几处。来历是 `03-novelai-composition-research.md`、`04-post-image-prototype.md`、`11-post-image-prompt.md`；调研全文在 `research/moments-novelai-composition` 分支（第 6.2–6.4 节），图库和出图脚本在 `prototype/moments-images` 分支。

**Blocked by:** 14

**Status:** done

- [x] **带不带图**写成纯函数：约 2/3 带。部署者没配生图时全部是纯文字。
- [x] **这次允许的构图**：六种（风景、食物、物品、自拍、摆拍、抓拍）。她自己没配 `photo_tag` 和 `photo_appearance` 时，只允许风景、食物、物品三种。
- [x] **提示词**：靠后那条系统消息最后加一节「这次允许的构图」，不带图时整节省掉。这一节里写：
  - `<image>` 一行一栏：`composition`、`framing`、`place`、`outfit`、`action`、`note`；
  - 只能选这次允许的构图。
  
  规则里再加：
  - 文字不依赖配图，配图没发出来也读得通。
  - 写街景时，写站在地面能看到的东西。
  - 风景、食物、物品的 `action` 栏写景物、食物或物品，`outfit`、`framing` 不用写。
  - 摆拍和抓拍可以选 `wide shot`。
  - 工作那条从做完的几项里挑一项来配图。
- [x] **解析** `<image>`：遇到这几种情形就改发纯文字，记一次降级：
  - 构图不在这次允许的里面；
  - 选了物品、`action` 却是空的；
  - 整栏解析不了。
  
  写了这个构图不允许的景别，退到 `upper body`，不算写坏。
- [x] **各构图的提示词**照规格「配图的提示词」写：
  - **风景**：前缀是 `no humans, scenery, japan, outdoors, {style}, {place}, {subject}, Q`。
  - **食物、物品**：不补 `japan`、`outdoors`。
  - **无人的三种**（风景、食物、物品）：
    - 去掉人、角色、外貌和作品的 tag，负面加 `1girl, 1boy, people`；
    - `action` 放在 `{subject}` 的位置；
    - 食物的 `action` 是空的就补 `food`。
  - **摆拍**补 `looking at viewer`。
  - **抓拍**：
    - 去掉 `looking at viewer`；没写视线时补 `looking away`，负面加 `looking at viewer`；
    - 写死 `depth of field`。
  - **景别**：
    - 摆拍、抓拍五档，比现在多一档 `wide shot`；
    - 自拍只有 `portrait`、`upper body`。
- [x] **清洗**复用照片的管线，照调研 6.3、6.4 落地，不删减：
  - 无人构图另外剥 `1girl`、`solo`、`selfie`、`looking …`、`holding …`。
  - 黑名单 `people` 类补 `viewer holding phone`、`solo focus`。照片也跟着生效，这是有意的。
  - 单人和无人构图剥 `holding hands`。
  - 6.4 的种子和改写表加进生成本地 tag 表的脚本，然后重跑。只查 tag 建议，不出图。
- [x] **尺寸**：风景 1216×832，其余 832×1216。生图客户端改成按请求的尺寸发、按请求的尺寸检查返回，NovelAI 和 OpenAI 两种形态都要改；照片照旧是 832×1216。
- [x] **排队**：
  - 配图和照片在部署者的生图 key 上排同一个队。用户要的照片插到等着的配图前面，正在生成的不打断。
  - 配图的时限是 10 分钟，排队也算在里面；超时就发纯文字。
  - 配图从不用用户自己的 key，也不计入照片的每小时限额。
- [x] **先后**：配图在写下动态之前生成好（或者失败）。文字写下的那一刻才是露出时间。
- [x] **存储**：新表「配图」，一条动态最多一张。照 ADR-0024 转成 WebP，去掉全部元数据。登记进 `USER_DATA`。动态里存她写的各栏、构图和 `note`。
- [x] **取图接口**：照照片的写法，只有本人能读，同源、要登录。别人读不到，管理者也读不到，后台不出查看入口。
- [x] **运行记录**：
  - 生图调用记在这条 `moment` 下，花费自动进看板；照照片记下被剥掉的 tag 有几个、各属黑名单的哪一类，不记 tag 本身。
  - 配图失败时，动态照样记成功，失败的生图调用另有记录。
  - 在队列里等到超时、没发出请求的，不算生图服务失败。
- [x] **最近 5 条**：防重复那一节里，每条加上「（配图：<note>）」。
- [x] **时间线接口**：配图给出取图的地址，没有时为空。
- [x] **前端**：字幕下面放一张窄的缩略图，点开用 `ImageViewer` 放大。横图、竖图都不变形。
- [x] **测试**：都走「跑一遍」和 `FakeImageService`，看发给生图服务的请求体：
  - 六种构图的提示词、负面、尺寸；
  - 清洗：无人构图另外剥的、`viewer holding phone`、`solo focus`、`holding hands`；
  - 她没配外貌时只允许无人构图；
  - 部署者没配生图时全是纯文字；
  - 配图失败、超时时发纯文字；
  - 照片插队：用 gate 卡住一张配图，后面排着另一张配图和一张照片，照片先拿到位置；
  - 被剥 tag 的计数；
  - 取图接口：别的用户读不到，没登录读不到；
  - 带不带图的纯函数用 `FakeRandom` 测。
  
  先例：`test_photos.py`、`test_photo_all_ages.py`、`test_photo_records.py`、`test_photo_failures.py`、`test_image_service.py`。
- [x] **验收**：在本地构建版上用假生图造一条带图的动态，用 Playwright 看缩略图和放大，宽屏和手机各看一次。要用真中转出图看效果时，先向用户报张数，等他点头再出。
- [ ] 表结构有改动，部署前手动备份数据库。
- [x] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

## Comments

### 票 20 交接

- `POST_RULES` 里偶像评论那条现在只写「评论只回应正文里写出来的东西」。带图以后改成「正文和配图里写出来的东西」（规格「规则要点」），给评论的人看的配图描述用 `note`。

### 实现说明（票 21）

- **`photo_prompt`**：新增 `Composition`（六种）、`UNPEOPLED`、`PictureTag`、`tag_fields`、`read_picture(fields, allowed, idols)`、`picture_prompt`；`ImagePrompt` 多了 `size`（`PORTRAIT`/`LANDSCAPE`）。清洗共用 `_field`，新增 `drops`（各构图另外丢掉的，不计数）和 `alone`（剥 `holding hands`，计为 `people`）。无人构图另外丢掉 `1girl`、`solo`、`selfie`、`looking …`、`holding …`、作品 tag，以及她本人和圈子里各人的 `photo_tag`；有人的构图丢掉 `no humans`，抓拍再丢 `looking at viewer`。
- **`image_generation`**：去掉写死的 `WIDTH`/`HEIGHT`，NovelAI 和 OpenAI 两种形态都按 `prompt.size` 发、`kept_as_webp(picture, size)` 按它查。照片照旧 832×1216。
- **`photos`**：队列从 `Semaphore` 换成 `_Queue`，照片和配图两条等待队列，放位置时先给照片；新方法 `Photos.picture(character, tag, until)` 给朋友圈用，只走部署者的 key，不计照片限额，生图调用经 `timed` 记在当前运行记录下（含被剥 tag 计数）。
- **`moment_draws.draw_compositions`**：带不带图和允许的构图，`PICTURED = 2/3`。
- **`moment_prompt`**：`PostMaterial.compositions`；「这次允许的构图」一节放最后；`POST_RULES` 加了配图的几条规则和 `<image>` 的格式行，偶像评论那条改成「正文和配图里写出来的东西（配图看你写的 note）」（票 20 交接）；`parse_post` 读出 `Post.picture`，写坏记降级 `image`；`recalled(ja, note)` 给最近 5 条加「（配图：…）」。
- **`moments`**：新表 `moment_images`（登记进 `USER_DATA`）；配图在写下动态之前生成，时限 `PICTURE_TIME_LIMIT` 10 分钟（含排队），失败或超时照发纯文字、记成功；`moments.image` 存她写的各栏 JSON；`Moments.picture` 给取图接口。
- **接口**：`GET /api/moments/{id}/image`，只有本人能读（30 天内、已露出），缓存头照照片；时间线的 `image` 是这个地址或 null。
- **前端**：`MomentsPage` 字幕下面加缩略图（按原比例缩进 160px 见方），点开用 `ImageViewer`；`DESIGN.md` 补了「配图」一条。
- **tag 表**：`scripts/photo_tags.py` 加了 6.4 的种子和改写表（改写目标写空串表示剥掉），`people` 类补 `viewer holding phone`、`solo focus`，重跑后 `photo_tags.json` 已知多了 328 个，改写 8 条全收。
- **判断**：
  - `holding hands` 照片也剥（用户定的，计为 `people`），合照（票 22）放行。
  - 允许带图却没写 `<image>` 算写坏、记降级；没让带图时写了不读、不记。
  - 风景的 `action` 空着不补默认值；无人构图另外丢掉的那几类不计入被剥 tag 的计数，`holding hands` 计。
  - 时间线的 `image` 只给地址，不给尺寸；缩略图载入前没有占位。
- **验收**：本地构建版塞了一张竖图、一张横图的动态，宽屏和手机都看过：缩略图 109×160、160×109，放大不变形。没有用真中转出图。
