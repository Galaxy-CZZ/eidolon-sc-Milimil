# 11: 拍板：配图的提示词细节

Type: grilling
Status: resolved
Blocked by: 06, 10

## Question

构图枚举、前后缀、合照（两人和三人）、尺寸按构图定都已有结论（「调研：NovelAI 非自拍构图和多角色」第 6 节、「原型：配图实测」）。写规格前还要定这些细处：

- **风景在哪国**：只写 `street, dusk, city lights` 会画成俯瞰城市甚至欧洲小镇。补 `japan`，还是从地点池的条目带景物 tag（要地点池加字段的话，和「拍板：地点池怎么整理」对一下）；补了以后要不要出几张图验证。
- **桌边抓拍看镜头**：吃喝时 3/3 看镜头。接受（当成朋友对面拍她），还是修：抓拍默认补 `from side`/`profile`、正面写负权重 `-1::looking at viewer::`、吃喝时自动改成摆拍。修的话要出图验证。
- **她写的栏怎么清洗**：每种构图剥什么（无人构图剥 `1girl`、`solo`、`selfie`、`looking …`、`holding …`；单人和无人构图剥 `holding hands`），`people` 类补 `viewer holding phone`、`solo focus`，本地 tag 表补哪些种子、改写表加哪些（调研 6.3、6.4 的清单照搬还是删减）。
- **合照**：三人时 base 写 `group picture` 还是 `side-by-side`；「和谁」的人选范围（同组合、资料里有关系的）和任一人缺 `photo_tag`/`photo_appearance` 时怎么降级；OpenAI 形态的中转不提供合照时她怎么知道。
- **她给别的偶像拍**（单人提示词，主角换成别人）开不开放。
- 发请求时 `use_coords` 怎么写：返回的元数据把 `false` 记成了 `true`，要不要管。

## Comments

### 「拍板：地点池怎么整理」交接

地点池不加给生图用的 tag 字段：每个地点只有一句中文 `note`（告诉她这是什么地方）和 `category`，她写配图时看 `note` 自己写景物。「风景在哪国」只能靠固定补 `japan` 一类的前后缀，或者按类别补（类别 14 个，见那张票），不能指望从地点条目带 tag。

### 「拍板：一条动态里有什么、素材怎么挑」交接

- 她写的是 `<image>` 一栏，分栏照照片标签：`composition`（七种之一，只能是服务器这次允许的）、`framing`（有人的构图才写）、`place`/`outfit`/`action` 三栏英文 tag（无人构图只用 `place` 和 `action`）、`with`（合照里的人）、`note`（中文，不发给生图服务）。这里定每种构图各栏怎么清洗、补什么前后缀。
- 带不带图、能不能合照由服务器在调用前掷好告诉她；OpenAI 形态不提供合照时，「这次允许的构图」里就没有合照，她不用另外知道。
- 合照的人从这条动态的圈子里选（同组合 > 「人物关系」里写到的 > 偶尔别的组合），只能选配了 `photo_tag` 和 `photo_appearance` 的，1–2 人。圈子由服务器抽，提示词里只列配齐了的给她选，所以「任一人缺字段时怎么降级」只剩一种情况：圈子里一个配齐的都没有，这次就不允许合照。

## Answer

前后缀、清洗表照调研 6.2–6.4 落地，只改了风景的前缀和合照的拍法。为此出了 8 张验证图，全部能用。

- **风景补「在日本」**：前缀改成 `no humans, scenery, japan, outdoors, {style}, {place}, {subject}, Q`，食物和物品不补。只补 `japan` 时不再像欧洲小镇，但 `street` 仍画成高处俯瞰的古镇（J1，2 张）；再补 `outdoors`，景物写站在地面能看到的东西（`sidewalk, power lines, vending machine`），两张都成了平视的日本住宅街（K1，2 张）。所以动态的提示词里要让她写街景时写地面能看到的东西，交给「拍板：动态的提示词和评测」。公园秋叶（J2，2 张）也可以用。负面不用加 `aerial view` 一类的词。
- **桌边抓拍看镜头不修**：吃喝时她照样会看镜头，画面像朋友坐对面拍她。抓拍照常补 `looking away`，负面加 `looking at viewer`。规格里记作已知现象。
- **无人构图的 `action` 栏装景物、食物或物品**，放在前缀里 `{subject}` 的位置，不加新栏，`outfit`、`framing` 忽略。食物的 `action` 是空的就补 `food`；物品的 `action` 是空的，按 `<image>` 写坏处理，这条发纯文字。
- **清洗照搬调研 6.3、6.4，不删减**：无人构图另外剥 `1girl`、`solo`、`selfie`、`looking …`、`holding …`；`people` 类补 `viewer holding phone`、`solo focus`；单人和无人构图剥 `holding hands`，合照放行；6.4 的种子和改写表全部加进 `scripts/photo_tags.py`，然后重跑。人数 tag、每个人的 `photo_tag` 和 `photo_appearance` 由服务器写进 base 或角色框，不经过清洗；`read_tag` 去重用的固定集合按实际人数换。
- **景别**：摆拍和抓拍在现有四档上加 `wide shot`，一共五档（神社前 2 张，人小景大、认得出、手没画坏）。自拍只有 `portrait`/`upper body`。写了这个构图不允许的景别，就退到 `upper body`，不算写坏。
- **合照不加「拍法」栏**：她在 `action` 里写了 `selfie`（合照里不剥），就用 `{n}girls, selfie` 的 base，景别收到 `portrait`/`upper body`；没写就是别人拍，两人写 `2girls, side-by-side`，三人写 `3girls, group picture`，景别 `upper body`/`cowboy shot`。`outfit` 全员共用。选了合照但 `with` 是空的或者不在可选名单里，就降成她一个人的摆拍，景别保留。人选范围和 OpenAI 形态的处理已在「拍板：一条动态里有什么、素材怎么挑」定下。
- **不给别的偶像单独拍**：偶像之间的互动由合照覆盖，记进 Out of scope。
- **`use_coords` 不管**：照现在发 `false`、centers `(0,0)`。返回的 PNG 元数据把合照记成 `true`，不影响出图；规格里记一句，免得以后有人去「修」。
- **不开 GPT Image 系列的调研票**：NovelAI 出的无人构图，原型 5 张加这次 6 张都没有质量问题，剩下的只是提示词怎么写。记进 Out of scope。

验证图和脚本在远端分支 `prototype/moments-images` 的 `.scratch/moments/prototype/images/verify/`（`index.html` 是图库，`verify.py` 能重跑）。
