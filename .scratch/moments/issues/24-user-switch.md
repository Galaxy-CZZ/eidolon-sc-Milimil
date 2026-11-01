# 24: 用户的开关

**What to build:** 用户在设置里有单独一类「朋友圈」，里面一个开关。关掉以后，导航里的「朋友圈」消失，不再给他发动态，她也不再回他的评论。已有的动态不删，照常过期；重新打开后接着发。部署者没开朋友圈时，设置里没有这一类。规格见 `../spec.md`：「开关关着的时候」全节；「接口」里讲账号和设开关的两处；「前端」里讲设置的一处。

**Blocked by:** 14

**Status:** done

- [x] **存储**：新表 `moments_off`，只记关了的用户，照 `reach_outs_off` 的写法；登记进 `USER_DATA`。
- [x] **账号字段** `moments`：部署者关着时为空，开着时是用户自己的开关，默认开。
- [x] **设开关的接口**：照搭话的写法；部署者关着时拒绝（409）。
- [x] **关着时**（只作用在他自己身上）：
  - 不给他排计划；已经排了、还没到点的，到点时跳过。
  - 时间线、赞、评论、取图的接口都拒绝（409）。
  - 到点的回复（23）：到点时判断他关着，就不回。23 已经做了，就在这一张加上；还没做，就在 23 的 `## Comments` 里留一句交接，由 23 做。
  - 已有的数据保留，照常 30 天过期。
- [x] **重新打开后**：当天已有计划、还没到点的，照常发；还没排的，下一次 tick 从当天剩下的时间里排。
- [x] **前端**：
  - 设置里加一类「朋友圈」，放在「搭话」后面。一级列表的摘要写「开」或「关」。
  - 二级页只有一个开关，拨了马上存到服务器；存不上就拨回去，并提示。没有说明小字。
  - 账号里朋友圈为空时没有这一类；直接打开它的网址，回到设置页。
  - 他关了以后，导航里的「朋友圈」不出现。
  - `settingsCategory.test.ts` 测这一类的位置、摘要，以及为空时没有这一类；`navShell.test.ts` 测他关了时没有这一项。
  - `DESIGN.md` 的设置页补上这一类。
- [x] **测试**，照 `test_reach_out_switch.py` 的写法：
  - 默认开；拨了就存下；部署者关着时拒绝。
  - 关着时：不排计划，到点的跳过，回复不生成，各接口 409。
  - 重新打开后，当天剩下的照常排、照常发。
  - 新表登记（`test_database.py`）。
- [x] **验收**：在本地构建版上用 Playwright 关掉、打开，看导航的变化、设置里的摘要，以及存不上时拨回去。
- [ ] 表结构有改动，部署前手动备份数据库。
- [x] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

### 票 14 交接

- 账号的 `moments` 现在由 `Moments.switch_of(user_id)` 给：部署者开着时 `True`，关着时 `None`（没看参数）。前端 `navItems(moments)` 只在 `=== true` 时带「朋友圈」，换成用户开关后 `false` 也就自然隐藏。
- 部署者关了再开时，`run_due` 会清掉全部计划和 `moment_users.planned_day`；用户自己的开关不要照搬这个（只清他自己的，或者按规格「当天已有计划的没到点照常发」）。

### 票 23 交接

- 到点的回复（23）已经做了，「他没关自己的朋友圈」由这一张加：`Moments._reply` 开头那串条件里加一条，不满足就照其他条件一样 `_no_reply`、不留记录。
- 赞、取消赞、发评论、删评论都先过 `Moments._on_timeline`，他关着时在那里抛 409 就一起拦住了。

### 实现说明（票 24）

- **存储**：`moments_off`（只有 `user_id`），照 `reach_outs_off`；登记进 `USER_DATA`。
- **后端**（`moments.py`）：`switch_of` 改成 async，部署者关着为 `None`，否则读 `moments_off`；新加 `switch(user_id, on)`，部署者关着抛 `MomentsOff`。`PUT /api/account/moments`（`MomentSwitch`，`StrictBool`）照搭话，409「朋友圈没有开放」。
- **关着时**：
  - `_standing` 的 `active` 多一条「他没关自己的」。排计划（`_unplanned`）和到点的判断（`_still`）都走它，所以关着时不排；已排的到点跳过，删掉那行计划，不留记录。
  - 他关着时不排，也就不记 `planned_day`。重新打开后，下一次 tick 按「够格后的第一次 tick」从剩下的时间里排；已排、还没到点的照常发。
  - 回复：`_BeforeReply` 多一个 `switched_on`，`_reply` 开头那串条件里加一条，不满足就 `_no_reply`，以后也不补。
  - 时间线、取图、赞、评论、删评论都先过 `_require_on`（部署者和他自己任一关着就抛 `MomentsOff` → 409）。
- **前端**：
  - `settingsCategory` 的 `SWITCHED` 加了 `moments`，`SettingsSwitches` 多一个 `moments`，位置在「搭话」后、「周期」前。
  - 新组件 `MomentsSettings`（照 `ReachOutsSettings`），开关文案「她们会发朋友圈」；`api.switchMoments`；图标用导航的 `MomentsIcon`。
  - 导航本来就只在 `moments === true` 时带「朋友圈」，`navShell.test.ts` 也已经测了 `false`，没有改。
  - 朋友圈页碰到 409 换到对话列表，他关了以后直接打开 `/moments` 也走这条。
- **判断**：
  - 他自己关着时 409 的提示也是「朋友圈没有开放」（同部署者关着）。朋友圈页碰到 409 直接跳走看不到；只有另一个标签页里还开着朋友圈页时去赞、评论才会看到这句。
  - `DESIGN.md` 设置页那节原来漏了「周期」这一类（写的是「十类」），这次连同周期一起补上，类数改成十二。
  - 已有的动态照常留着、30 天过期，没改 housekeeping。
- **审查**（code-review，两轴）：
  - 已修：去掉测试里 `{"on": "no"}` → 422 那半（`StrictBool` 本来就保证，`CODING_STANDARDS.md`「Holds by construction」）；`_have` 改名 `_require_on`。
  - 只报告、没改：用户开关的读写（`_switched_on`/`_switch`）、`MomentsSettings` 和 `ReachOutsSettings`/`CyclesSettings`、后端的开关模型和路由、`api.ts` 的 `switch*`，都已经是第三份同样的写法，可以抽成按名字参数化的一份；加一个「部署者开了才有的用户开关」要改约 9 处（前端已有 `SWITCHED` 表收拢了一半）；409 那条测试一个断言盖了 6 个接口，没有按接口标注（照 `test_moment_producer.py` 的写法）。
- **验收**：本地构建版（后端临时开 `EIDOLON_MOMENTS=1`），开发用户各在宽屏和手机上走了一遍：
  - 默认摘要「开」、导航有「朋友圈」。
  - 拨关后 PUT 204，导航回到三项，摘要「关」，`/api/moments` 409；刷新后仍是关。
  - 拨开后导航回来。
  - 拦下 PUT 回 500 时拨回开、导航不变，下面出提示。
  - 把 `/api/account` 的 `moments` 换成 `null`：直接打开 `/settings/moments` 回到 `/settings`，一级列表和导航都没有这一类。
  - 本地 `.env` 没开搭话，看到的顺序是「通话、朋友圈、周期」，「搭话 → 朋友圈」的位置由 `settingsCategory.test.ts` 测。
  - 验收用户已删，脚本和截图都删了。
- 表结构有改动（新表 `moments_off`），部署前照例手动备份数据库（留给部署时）。
