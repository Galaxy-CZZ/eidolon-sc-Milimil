# 29: 评测命令和 18 个场景

**What to build:** 维护者跑一条命令，十几个场景就逐个交给模型，生成动态和回复，连同配图清洗后的最终 tag 串写进一份 HTML。格式坏了、超字数、名单越界这类问题，机器在 HTML 里标出来；读起来像不像她、有没有说漏私事，由人读。改提示词前后各跑一遍，就能对照。这张票也是前面几张票里提示词措辞的验收：用户读过 HTML、点头才算定稿。规格见 `../spec.md` 的「评测」一节，来历是 `13-post-prompt-and-eval.md`。

**Blocked by:** 18, 19, 22, 23

**Status:** done

- [x] **命令** `eidolon eval moments --html <文件>`：
  - 默认用部署者的对话模型，`--model` 可以换；每个场景默认跑 1 遍，`--runs N` 跑 N 遍。
  - 不真的生图，只写出清洗后的最终 tag 串。
- [x] **场景文件**：后端评测目录下的 `moments.toml`。记忆和日程都是编的，不用剧情原文（ADR-0003）。
- [x] **直接喂素材，不建临时库**：
  - 发动态的场景写好这次给她的全部素材：角色、档位、周期、时间、`today_lines`、天气、做完的工作或 3 条资料种子、记忆、最近 5 条动态、圈子成员、地点候选、带不带图、允许的构图、是不是 NovelAI 形态。
  - 回评论的场景写：动态正文和 `note`、已经露出的评论、他赞没赞、最后几个回合、他的评论原话。
  - 命令和线上用同一个拼提示词的函数、同一个解析器。
- [x] **机器检查不判通过**：
  - 要查的有：格式能不能解析、各部分的降级、字数、地点 id 在不在候选里、名单是不是都在圈子里、构图在不在允许的范围内、合照里的人有没有算进赞。
  - 降级和超字数在 HTML 里标出来，终端打一行计数。
  - 只有命令本身出错时才返回非零。
- [x] **18 个场景**，覆盖 5–6 位性格不同的角色：
  - 发动态 12 个：
    1. 工作那条，一天两项工作串成一条；
    2. 日常那条，只有资料种子；
    3. 她生日（圈子 8–10 人）；
    4. 制作人生日；
    5. 下雨，候选只有室内的；
    6. `today_lines` 里有同组合伙伴的生日；
    7. 记忆里埋一件他私下说的事；
    8. 亲密档（看有没有情侣口吻）；
    9. 允许合照，NovelAI 形态；
    10. OpenAI 形态，不允许合照；
    11. 掷到纯文字；
    12. 最近 5 条全在说同一件事。
  - 回评论 6 个：
    1. 亲密；
    2. 亲近；
    3. 信任；
    4. 他的评论问到私事；
    5. 偶像评论里已经有人说了相近的话；
    6. 他只写了「かわいい」。
- [x] **人工**：场景初稿在 `E:/tmp/` 生成 HTML 给用户校对，校对完再提交。
- [x] **人工**：本机用 `deepseek-flash` 跑一遍，HTML 交给用户读。用户要看的是：
  - 日语和字幕对不对得上；
  - 偶像评论有没有提正文里没写的事；
  - 私事有没有被点明；
  - 有没有写成情侣口吻；
  - 和最近 5 条重不重复；
  - 配图的 tag 写得好不好，比如街景里要有站在地面能看到的东西。
  
  读出问题就改提示词的措辞（14、17–23 写的那些规则），再跑，直到用户点头。
- [x] **测试**，照 `test_memory_eval.py`：
  - 用两三个场景的小文件，`FakeLLM` 分别答出好的和坏的输出。
  - HTML 里有动态、回复、清洗后的 tag 串，坏的部分标了出来。
  - 终端打出计数；返回值对。
- [ ] `sh scripts/affected-tests.sh <基点>` 通过，推送后 CI 全绿。

## Comments

### 票 19 交接

- 工作那条的素材是 `PostMaterial.jobs`（每项写成「名字：note」，按做完的先后），这时 `seeds` 为空；地点候选只来自这几项工作的 `places`（`draw_places(..., within=)`），都没写就是空。场景文件要能写出这两样，才评得到工作那条。

### 票 22 交接

- `draw_compositions` 现在要传第四个参数 `group`。场景 ⑨ 要允许合照，`PostMaterial.compositions` 里要带 `"group"`，圈子里至少一位配齐了 `photo_tag` 和 `photo_appearance`；场景 ⑩ 不带。
- 「合照里的人有没有算进赞」：`parse_post` 会自动把合照里的人补进 `Post.likes`，所以只看 `Post.likes` 总是对的。要查她自己写没写，得拿 `<likes>` 原文和 `post.picture.tag.others` 比。降成摆拍记在 `degraded["with"]`。

### 票 23 交接

- 回评论走 `moment_prompt.reply_prompt(ReplyMaterial)` 和 `parse_reply`，素材全在 `ReplyMaterial` 里（历史是已经截好的 `ChatMessage`，偶像的赞和评论用名字）；此刻那几行用 `HerNow.lines(..., "moments", ..., replying=True)`。

### 实现说明（票 29）

- 新模块 `moment_eval.py`：`load_moment_eval(path, characters, places, world)` 读 `eval/moments.toml`，每个场景拼成 `PostMaterial`/`ReplyMaterial`；`evaluate(eval, llm, runs, style, progress, at_a_time=4)` 走 `post_prompt`/`parse_post`、`reply_prompt`/`parse_reply`，配图走 `picture_prompt`（画风取 `NOVELAI_STYLE`）；`check_post` 标出降级（附原因：写的是哪个地点、为什么没图、越界的是谁）、合照里的人没写进赞、不带图却写了 `<image>`，超字数（正文 100、偶像评论 40）单列；`summary_line` 打一行计数（「有降级」只数 `Post.degraded`）；`render_html` 写成 HTML，每个场景带「给她的素材」和模型原文。
- 命令 `eidolon eval moments --html F [--file] [--model] [--runs] [--characters]`，模型照 `eval memory` 的先例取环境变量里的对话模型（`CHAT_LLM_*`），不读后台改过的设置。模型出错记进 HTML，只有命令本身出错（场景文件、配置、写不了 HTML）才返回 1。
- 为了和线上走同一套函数，`moments.py` 的 `_relations`、`_said`、`_written` 改成公开的 `relations`、`said_to_chat`、`written_whole`；`memory.py` 加 `posting_memories_prompt`。此刻那几行照 `HerNow.lines` 的「moments」场合拼：`posting_now_prompt` → 场景写的 `today` → `cycle_lines`。
- 场景：6 位角色（真乃、恋鐘、円香、あさひ、冬優子、凛世）各 3 个；资料种子照线上的 `_seed` 写法取自角色资料，记忆、最近的动态、对话是编的，`today` 是用 `today_lines` 按场景日期算出来抄进去的。记忆的日期按制作人时区的当天零点（不写时区按 Asia/Shanghai），和提示词里显示的日期一致。
- 用户 10-31 校对场景、读了 `deepseek-flash` 跑的 HTML，认为没有问题，提示词措辞不改。读到的现象留作记录：偶像评论常超过 40 字（霧子带空格的写法尤其长）；回评论 4 有一遍冬優子当众承认了「激辛」那件事（规则只说他私下告诉她的事不点明，没管她自己不对外说的事）；⑧ 凛世织手套「给谁的是秘密」。
- 审查里的判断题，没改：评测里的 100、40 字和 `POST_RULES` 的数各写一份；`moment_eval` 读 `<likes>`、`<place>` 原文的几个正则和 `moment_prompt` 的重复（只为标出原因）；已提交场景集的测试写死 12 + 6；除 ⑩ ⑪ 外的发动态场景都允许合照，⑨ 不算特别（照线上 NovelAI 形态的实际情况）。
