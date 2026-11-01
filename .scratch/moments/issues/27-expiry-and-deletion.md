# 27: 30 天清理和删除

**What to build:** 朋友圈只留最近 30 天：过期的动态连同配图、赞、评论、她的回复，一起自动删除。删除用户时，他的朋友圈全部删掉；删历史对话不影响朋友圈；数据包里没有朋友圈。规格见 `../spec.md`：「存储」里讲清理的一条，以及「数据包、删除、备份」。

**Blocked by:** 21, 23

**Status:** done

- [x] **`housekeeping` 加一项**：按露出时间删 30 天前的动态，一起删掉的还有：
  - 配图；
  - 其他偶像的赞和评论；
  - 制作人的赞、评论，以及她的回复（还没露出的也删）。
  
  照现有的写法分批删（`in_batches`），每批是一个单独的写任务。
- [x] **发布计划**：漏下的那几行（计划那天在东京的前天或更早），由 `housekeeping` 删掉。
- [x] **30 天内用过的地点**：照旧按动态表算，过期删掉的动态自然不再排除那个地点。
- [x] **删除用户**：朋友圈的各张表都登记在 `USER_DATA` 里，全部一起删。
- [x] **删历史对话**：朋友圈不受影响。
- [x] **数据包**：导出里没有朋友圈，导入也不碰它，格式版本不变，格式说明文档不用改。
- [x] 备份是整个数据库，自动带上，不用做什么。
- [x] **测试**：
  - 刚满 30 天的被删掉，没满的留着；连带的那些也一起删；分批删也删得完（照 `test_housekeeping.py`）。
  - 漏下的计划被删掉，今天和昨天的留着。
  - 删除用户后，朋友圈的各张表里都没有他的数据；新表都已登记（`test_database.py`）。
  - 删历史对话后，动态还在（照 `test_delete_past_conversations.py`）。
  - 数据包导出里没有朋友圈（照 `test_data_package_reach_outs.py`）。
- [x] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

### 票 21 交接

- 新表 `moment_images`（`moment_id` 主键，`image` 是 WebP）已登记进 `USER_DATA`。30 天清理删动态时要连它一起删，放在删 `moments` 之前。

## Comments

### 票 23 交接

- 清理时连 `moment_likes`、`moment_comments`（包括还没露出的回复）一起按动态删；两张表在 `USER_DATA` 里排在 `moments` 前面。

### 实现说明（票 27）

- `Moments.forget_old`（`moments.py`）：按露出时间删 `posted_at <= 此刻 - KEPT` 的动态，和时间线的 30 天口径（`posted_at > 此刻 - KEPT`）正好接上。先逐表删 `moment_images`、`moment_circle`、`moment_likes`、`moment_comments`（她的回复在评论行里，没露出的也一起删），最后删 `moments`。每张表各走一遍 `in_batches`，每批最多 `BATCH` 行。不看开关，关着照常过期。
- 同一个方法里删漏下的计划：`day < 东京昨天`，也就是前天及更早的，同样分批删。
- `assembly.py` 把 `moments.forget_old` 加进 `keep_tidy`；`housekeeping`、`moments` 两个模块的文档都补了这一项。
- 删除用户（`USER_DATA` 早已登记）、删历史对话、数据包三项不用改代码，只补了测试：`tests/test_moment_expiry.py`。
- 审查后改动：起初是每批 1000 条动态连同它的子行，一个写任务删的行数会是 `BATCH` 的几倍，所以改成逐表按行数分批。
- 判断题，没改：
  - 子表名在 `_WITH_A_MOMENT`、`USER_DATA`、测试的 `MOMENT_TABLES` 里各写了一遍。测试里那份当作独立的事实来源，故意不复用。
  - `moments.posted_at`、`moment_plans.day` 没有单独的索引，每次清理都是全表扫。表不大（每位用户最多约 90 条），没加。
  - 一批 1000 张配图开着 `secure_delete`，覆盖写的量不小。平时每 10 分钟只删十分钟里过期的那些，只有停机很久后堆积才会碰到，暂不单独调小。

