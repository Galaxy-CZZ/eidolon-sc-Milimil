# 07: 她记得自己写过的信

**What to build:** 制作人在对话或通话里提起她写的信时，她接得上：知道自己哪天、为什么写过信，信里写了什么。她搭话时也记得。

见 spec「她记得自己写过的信」。

**Blocked by:** 01

**Status:** done

- [x] 文字回合、通话里的回合、搭话，每回合变的那条系统消息里加一节「你写给制作人的信」：她写给这位制作人的最近 3 封，每封日期、场合、全文（去掉语气提示）；没有信不加。
- [x] 这一节不进共用的固定部分，不破坏前缀缓存。
- [x] 删掉的信不再出现；别的角色写的信不出现。
- [x] 测试照 `test_dynamic_context.py`、`test_reach_outs_in_turns.py`：经 HTTP 发起回合和调搭话的「跑一遍」，检查假 LLM 收到的请求。

## Comments

### 实现说明（票 07）

- **读信**：`letter_prompt.read_earlier(db, user, character)`（最近 `EARLIER` = 3 封，按 `written_at` 取，最早的在前），连同解开表里存法的 `stored_occasions`、`stored_written`，从 `letters.py` 挪到 `letter_prompt.py`，写信和回合共用。没放在 `letters.py`：`letters → moments → engine` 已经成环，engine 导入不了它；照 `recent_moments.py` 的先例放在下层。
- **这一节**：`letter_prompt.letters_section` 输出「# 你写给制作人的信」，每封的排法（`## 日期（场合）`、抬头、正文的日语、去掉语气提示）和写信请求里「以前的信」共用 `_recalled`，写信请求的输出逐字不变。
- **接到回合上**：`engine._read_before_asking` 在同一次读库里读信（`_BeforeAsking.letters`），文字回合、通话回合（`_reply`）和搭话（`reach_out`）都把这一节放在每回合变的那条系统消息里，紧跟「你最近发的朋友圈」。共用的固定部分和制作人那条不变。
- **测试**：`test_letters_remembered.py` 四条：文字回合（经升到亲近真写一封，前缀不变）、通话回合、搭话、只取她写给这位制作人的最近 3 封（删掉的、别的角色的、别的用户的不算）。
- **判断**：
  - 只给日语全文，不带中文翻译：中文是字幕，她自己的话是日语（和写信请求里「以前的信」一样）。
  - 这一节多一句规矩：「他提起时，你记得自己哪天、为什么写了什么；不用主动提起，也不要整段照念。」spec 没写，加上是免得她每回合都提信、或者整段背出来。
  - 总开关关着时照样告诉她：信还在、用户照样能看。
- **审查**：两份审查的修改已做（两处超长的文档串折行、`on` 改名、补别的用户的信不出现）。没改的判断题：`letter_prompt.py` 里多了 SQL（标准审查建议另开 `recent_letters.py`，但每封的排法是写信请求和这一节共用的，拆开要跨模块用私有函数）；`_letters_told` 和 `_moments_told` 写法一样，没抽公共函数；engine 里用的类型名还是 `Earlier`；通话那条测试和文字回合走同一条读信的路，按 spec Testing Decisions 点名要测通话回合留着。
- **本机测试**：`test_call_turns.py` 里已知的两条偶发（`SleepFrame(0.5)`、`one_by_one` 靠时间排序）并行跑时各挂过一次，单独跑改动前后都过。
