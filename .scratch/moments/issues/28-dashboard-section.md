# 28: 看板「朋友圈」一节

**What to build:** 部署者在看板的「用量」里看到一小节「朋友圈」：

- 这段时间发了几条动态、失败几次；
- 她回评论几次、失败几次；
- 最近 30 天的动态里，制作人赞过或评论过的占几成。

这样看得出这个功能有没有人在用。规格见 `../spec.md`「运行记录、看板、服务状态」里讲看板的一条；来历是 `09-storage-switches-dashboard.md`。

**Blocked by:** 23

**Status:** done

- [x] **什么时候出现**：朋友圈开着，或者范围内有过 `moment`、`moment_reply` 的记录。否则这一节在接口里为空，页面上也不出现。
- [x] **数从哪来**：
  - 发了几条、失败几次、回评论几次、失败几次：从运行记录写入时汇总好的数读，不新增写入。「被拒绝」的不算失败。
  - 制作人赞过或评论过的占比：分母是最近 30 天露出的动态，分子是其中他赞过或评论过的。打开看板时直接查动态表，不随范围变；没有动态时为空。只是所有用户合起来的数，不落到任何一位用户。
- [x] **不做的**：不按角色分，花费不单列（已经算在各项服务里），不进用户页。
- [x] **前端**：后台看板「用量」标签里加这一小节，写法照「搭话」那一小节，用 `dashboard.test.ts` 测。
- [x] **测试**，照 `test_reach_outs_dashboard.py` 的写法：
  - 四个数；占比的分子和分母，以及没有动态时为空。
  - 关着、范围内也没有记录时，这一节为空；关着但范围内有记录时，照样显示。
  - 花费归到各项服务。
- [x] **验收**：在本地构建版上造几条动态和回复，打开后台看板，用 Playwright 看这一节。
- [x] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

## Comments

### 票 23 交接

- 回评论的运行记录是 `moment_reply`：成功、失败（模型出错或解析不了），写下时评论已删记 `rejected`。
- 「制作人赞过或评论过的占比」：`moment_likes`、`moment_comments` 都按 `moment_id` 对 `moments`。

### 实现说明（票 28）

- 后端 `dashboard.py`：返回里加 `moments`，键是 `posted`、`posts_failed`、`replied`、`replies_failed`、`liked_or_commented_share`。四个数从 `tally.records` 里 `moment`、`moment_reply` 两类的汇总读，`rejected` 两边都不算。朋友圈开着、或者范围内有这两类记录时才有这一节，否则为 `null`。
- 占比在 `Moments.liked_or_commented_share()`（`moments.py`）里：打开看板时查 `moments`，分母是露出时间在 `(此刻 - KEPT, 此刻]` 里的动态（和时间线、清理同一个口径），分子是其中在 `moment_likes` 或 `moment_comments` 里有行的。所有用户合起来，不看角色还在不在，没有动态时为 `None`。
- 前端：`MomentsSection`、`momentTiles`（`lib/dashboard.ts`），`MomentTiles` 放在「用量」里「酒吧」下面，文案在 `copy.admin.dashboard.moments`。五张卡用 `TileGroup` 的默认网格，桌面一行五张；手机上两列，最后一张「近 30 天制作人赞或评论过」的标签会折成两行。
- 测试：`tests/test_moments_dashboard.py`（四个数和被拒不算失败；占比的分子分母、30 天外和没露出的不算、别的用户的也算、不随范围变；关着时有没有这一节；花费归到 `chat_llm`），`dashboard.test.ts` 加了 `momentTiles`。
- 验收：在本地构建版上往库里造了 3 条动态（1 条赞、1 条评论）、发失败 1 次、回评论失败 1 次、被拒 1 次，后端不开朋友圈（只靠范围内的记录让这一节出现，也免得真去调模型发动态）。Playwright 看到「发了 3 / 发失败 1 / 回评论 3 / 回失败 1 / 66.7%」，24 小时和 90 天的占比相同，桌面和手机都看过。验完库已恢复。
- 审查后改动：`failed` 改名 `posts_failed`，和 `replies_failed` 对称；删掉一条和别的测试重复的用例。
- 判断题，没改：
  - 「评论过」只算现在还留着的评论，删掉的不算。赞本来就只存现状，两边口径一致。
  - 用户自己关了朋友圈，他的动态照样算进分母。
  - 花费测试只看了对话模型，没覆盖带配图时的生图。配图的生图调用记在同一条运行记录下，走的是同一条路。
  - `MomentTiles` 和 `ReachOutTiles`、`BarTiles` 等几个小节组件几乎一样，可以抽成一个，这次没动。
