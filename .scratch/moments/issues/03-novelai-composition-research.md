# 03: 调研：NovelAI 非自拍构图和多角色

Type: research
Status: resolved
Blocked by: none

## Question

现在的照片提示词把「只拍她本人、多半是自拍」写死了（`backend/src/eidolon/photo_prompt.py`：`1girl, solo`、拍法只有 `selfie`/`other`、别人拍时补 `looking at viewer`）。配图要能拍风景、物品和食物、别人给她拍的、和其他偶像的合照。要查清楚：

- **成熟的提示词指南**：NovelAI（V4.5 / V5）以及 Danbooru tag 体系下，写风景、静物、食物、「朋友圈随手拍」风格的提示词有哪些可信的指南、仓库、网站（官方文档、NovelAI 官方博客和 Discord 整理、知名的 tag 指南仓库）。哪些 tag 决定构图（`no humans`、`scenery`、`still life`、`food focus`、`from behind`、`candid` 之类），哪些会和我们的画风插槽（`0.7::artist:rella::`）冲突。
- **他拍而不是自拍**：怎么让画面像朋友帮她拍的生活照，而不是摆拍立绘；`looking at viewer` 什么时候该去掉。
- **多角色**：V4 以后的多角色提示框（`v4_prompt.caption.char_captions` 加 `use_coords`）在 V4.5 和 V5 上的官方说明和社区实测效果：两三个人时外貌串不串、人数准不准、要不要给坐标。V5 Curated 支不支持；中转（OpenAI images 形态）会不会把这个字段吞掉。
- **人数上限和失败形态**：三人以上是否明显崩，常见的失败（多一个人、脸串了、手）。
- 起点：远端分支 `research/novelai-prompting` 上的 `.scratch/photos/research/novelai-prompting.md`（只实测了自拍，5.4 节提过 `char_captions`），以及 `.scratch/photos/issues/04`、`05`、`11` 的结论。
- 结论给出：建议的构图枚举、每种构图的固定前后缀草案、合照值不值得进 v1，以及原型实测要测哪几组（为「原型：配图实测」准备）。

## Answer

构图分七种，她从枚举里选，服务器补固定前后缀：风景、食物、物品、自拍、别人帮她拍（看镜头）、别人抓拍（不看镜头）、合照。前后缀草案见调研 6.2 节。

- 无人的三种以 `no humans` 打头，去掉 `1girl, solo`、角色 tag、外貌和作品 tag，负面加 `1girl, 1boy, people`。画风插槽（rella 爱画人在风景里）和质量 tag 会不会把人拉回来，要实测。
- `candid`、`group selfie` 不是 tag。抓拍靠：去掉 `looking at viewer`，没写视线时补 `looking away`、负面加 `looking at viewer`，加一个正在做的动作，写死 `depth of field`。`still life` 是「静物画」，改用 `food focus`、`object focus`；`background dataset` 出实拍风，和画风冲突。
- 多角色提示框 V5 Curated 也支持（官方上限 V5 22 人），结构 `char_captions: [{char_caption, centers:[{x,y}]}]`，负面同构；人数 tag 只写在 base，每个角色框写 `girl, <角色 tag>, <外貌>`。OpenAI images 形态的中转传不了，那种形态下不提供合照。
- 社区实测 2–3 个原创角色一般不串色，但谁搭谁的肩、左右手常画反；两个版权角色在 V5 Curated 上没人测过，只能靠原型。
- 合照有条件进 v1：只做两人、只在 NovelAI 形态下开，原型 6 张里至少 5 张人数对、认得出、不串色才进；三人暂缓。
- 黑名单不用「放行」：人数 tag 和外貌由服务器写进 base 和角色框，不经清洗。核对现状：`pose` 类按整词已经剥掉含 `pov` 的 tag（`pov hands`、`pov across table` 都会被剥），调研说的漏洞只剩 `viewer holding phone`、`solo focus`，要加进 `people` 类；单人和无人构图还要剥 `holding hands`（推断，没出图验证）。
- 本地 tag 表要补一批种子（`no humans`、`scenery`、`food focus`、`depth of field`、`side-by-side` 等，清单见 6.4 节）。
- 给原型的测试矩阵：必测 14 张、选测 6 张、最多 20 张（第 7 节），含同发色双胞胎（大崎甘奈、甜花）这一最难认的组。

详见远端分支 `research/moments-novelai-composition` 上的 `.scratch/moments/research/novelai-composition.md`。
