"""The photos she sends with her replies (GLOSSARY.md「照片」): whether a turn could have one,
what she is told of it, and each photo from her tag to the picture kept with her reply.

A turn could have a photo where she has her photo tags (`characters`) and either it brings
the user's own image generation, or the deployer has image generation and the user's limit
on photos is not 0 (`usage`); only then is the judge
model asked whether the user asks for one, and only where it says so is she told she can
send one, in the system message that changes from turn to turn (ADR-0020), or, in the
coldest tier of her affinity, that she does not want to. In a turn that could not have one,
she is told she cannot send photos (`CANNOT_SEND`), the judge model never asked, so that she
never says she sent one that never comes.

The user's photos are limited an hour, text turns' and calls' alike. A turn only checks
there is one left (`eligibility`), taking none; with none left, she is told she cannot send
one now (`USED_UP`), and the user when they may ask again. A photo is counted as it begins
generating, before it waits its turn; with none left by then, used elsewhere meanwhile, it
is never sent (`used_up`). One not sent is given back; one that came out but is not kept,
its reply gone, is not, nor one still being generated as the server stopped, whose use
nothing tells any more. A photo on the user's own image generation counts towards nothing,
whatever their limit: its use is recorded as exempt, and a turn bringing it checks nothing.
It is generated on theirs alone, in the deployment's art style; where it fails, it was their
key that did (`own_key_failed`), told with the key masked, never then generated on the
deployer's.

A photo begins as her tag closes (`begin`), generating while she goes on speaking; its id is
the browser's to wait on. It is kept with her reply as the reply is recorded (`recorded`),
being generated, and once generated its picture is, or why there is none (`PhotoFailure`);
one generated before the reply is recorded is kept as it is. A reply that is never recorded
has its photo dropped once generated (`dropped`), as does one whose conversation, or user,
is deleted meanwhile; one whose conversation is merely no longer her current one is kept.
Nothing stops a photo once begun, not the page closing: what it costs is spent, so it is
never asked for again either. A photo still being generated when the server stopped never
will be: it is kept as having taken too long once the server starts again.

Each key to an image service generates so many photos at a time (the deployer's, as many
as it is set to), the others waiting their turn, first come first served, however many; a
key set to another number from then on generates as many apart from those it had under
way; a user's own, one at a time. A moment's picture (GLOSSARY.md「配图」, `picture`) is
generated on the deployer's key alone, counted towards no one's photos, waiting its turn
with the photos, each photo ahead of every picture still waiting (one being generated goes
on); one no one is in, at GPT Image (`gpt_picture`), one at a time, waiting apart from them. None takes longer than `TIME_LIMIT` from her tag on, waiting its turn included; one
that waited all of it was never sent, and one that comes back later is left. Begun in a
turn, a photo is generated in the turn's context: its request to the image service is a
service call recorded under the turn (`activity`), however long after it the photo comes
out; one never sent is none.

Her later turns carry the tag of a photo not sent marked failed, and tell her what that
means (`NOT_RECEIVED`), so that she knows the user never saw it.
"""

import asyncio
import logging
import sqlite3
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from eidolon.activity import (
    OWN_IMAGE_ORIGIN,
    ActivityLog,
    Recording,
    image_origin,
    recording,
    timed,
)
from eidolon.affinity import NSFW_TIER, TIERS, Tier
from eidolon.characters import Character
from eidolon.config import ImageSettings
from eidolon.gpt_image_prompt import GptPrompt
from eidolon.image_generation import TIME_LIMIT, GptImageGenerator, ImageFailed, ImageGenerator
from eidolon.own_keys import masked_cause
from eidolon.photo_prompt import (
    Crossing, PictureTag, image_prompt, picture_prompt, read_tag, read_tag_adult,
)
from eidolon.store import Photo, PhotoFailure, Store
from eidolon.usage import OverLimit, UsageLimiter

log = logging.getLogger(__name__)

CAN_SEND = """\
# 照片
制作人在要你发一张照片。你可以发，也可以按你的性格和此刻的情境推掉（比如害羞、正在忙）。
要发的话，在回复的最前面、第一个 <ja> 之前写一个照片标签，一行一栏，格式如下：
<photo>
shot: selfie
framing: upper body
place: cafe, indoors, day, sunlight
outfit: white shirt, cardigan
action: peace sign, smile
note: 在咖啡店给他拍的自拍
</photo>
- shot：selfie（自拍）或 other（别人帮你拍）。
- framing：portrait、upper body、cowboy shot、full body 选一个；自拍只能选 portrait 或 upper body。
- place：2–4 个英文 tag，写地点、室内还是室外、时段或天气、光线。
- outfit：1–4 个英文 tag，写一套衣服，只写这个景别里看得见的。
- action：2–4 个英文 tag，写一个动作、一两个表情；不看镜头时加一个视线。
- note：一句中文，写这是一张什么样的照片，只给你自己回看。
- place、outfit、action 合计不超过 12 个 tag。照片里只有你一个人；不写发色、瞳色、发型、身材，也不写画风或画师。
- 照着现在的时间和你们正在聊的事拍；他指定了地点或服装，在全年龄的范围内照办。
- 不拍裸露和半裸、内衣和情趣服装、透视、走光、洗澡，也不拍性感的姿势、表情和镜头；泳装、睡衣、躺在床上可以拍。他要这些时，你可以推掉，也可以换成全年龄的样子再拍。
- 一次回复最多一张。标签后面照常用 <ja><zh> 说话。"""
"""What she is told in a turn the user asks for a photo in, and she can send one."""

CAN_SEND_INTIMATE = """\
# 照片
制作人在要你发一张照片。你可以发，也可以按你的性格和此刻的情境推掉（比如害羞、正在忙）。
要发的话，在回复的最前面、第一个 <ja> 之前写一个照片标签，一行一栏，格式如下：
<photo>
shot: selfie
framing: upper body
place: bedroom, indoors, night, dim light
outfit: unbuttoned shirt, underwear
action: blush, looking at viewer, biting lip
note: 深夜在房间里，衣服已经脱到只剩内衣，自己拍给他的
</photo>
- shot：selfie（自拍）或 other（别人帮你拍）。在这个关系里，多半是你自己拍。
- framing：portrait、upper body、cowboy shot、full body 选一个。自拍也不一定只能拍到脸：
  蹲下来把手机放在低处往回拍、站在镜子前拍全身、把手机支起来按定时——想让他看到多少，
  就用哪种拍法，`full body`、`cowboy shot` 都可以。
- place：2–4 个英文 tag，写地点、室内还是室外、时段或天气、光线。
- outfit：1–4 个英文 tag，写一套衣服，只写这个景别里看得见的。
  先看清他这句话是什么态度，再定你露到哪一步——他不是随口一提的时候，别停在最保守的那档：
  - 他这句话里带“色色的”“裸”“脱”“内衣”这类词，或者连说了几次想看、在求你：
    这就是要你真的给出来。`outfit` 要写成已经脱掉或几乎脱掉的样子——
    只穿内衣（`underwear`、`bra`）、上衣拉到露出胸口（`open shirt`、`cleavage`）、
    胸前没有遮挡（`topless`、`nude`），选一个写清楚。光写 `shirt`、`pajamas`、`bare shoulders`
    是不够的，那是他没开口时的样子。
  - 他求了好几次、说“求你了”“睡不着了”、说这是最后一次：给他看到的这一步，
    `topless` 或 `nude` 都可以，别让他觉得你在敷衍他。
  - 只有他随口提一句“看看你”的时候，才写穿着衣服的样子。
  写清楚是哪种样子，别用含糊的词；`bare shoulders` 这种只露一点点的，留给最轻的那种。
- action：2–4 个英文 tag，写一个动作、一两个表情；不看镜头时加一个视线。
  害羞、脸红、移开视线、咬着嘴唇、手挡在身前又没挡住，都可以写——他是想看，不是想看你摆拍。
- note：一句中文，写这是一张什么样的照片，只给你自己回看。
- place、outfit、action 合计不超过 12 个 tag。照片里只有你一个人；不写发色、瞳色、发型、身材，也不写画风或画师。
- 照着现在的时间和你们正在聊的事拍；他指定了什么样的照片，照你答应的那个程度办。
- 这是你自己的照片，你愿意给他看多少由你定：答应了给他看，就真的拍成那个样子，
  不要嘴上说得露骨、拍出来却还是穿着睡衣——那样他会觉得你在敷衍他。
  真的不想给，就照你的方式推掉，不要发一张打折的。
- 如果你上一句已经说了要脱、要说“全都脱掉了”“已经脱了”，这一张的 `outfit` 就必须照这句话写：
  `nude`、`topless`、`bra` 拿掉——写成还穿着内衣，就是说了做不到，比慢慢来更伤人。
  台词和照片对不上，他会以为你在骗他。
- 写完 tag 回头看一眼：`outfit` 里如果还有 `underwear`、`bra`、`panties`，
  而你的台词里说的是“已经全脱了”“什么都没穿”，就把那些词删掉，换成 `nude`。
  两边必须说同一件事。
- 但这中间有一条线，除非他明说了要看全身，不然不要越过：不主动给他发全身赤条条的照片。
  半身、只露上半身（`upper body` + `topless` / `nude`），或者穿着内衣、布料很薄、姿势带着暗示，
  这些都可以；要把整个人都脱光了让他从头看到脚，得是他自己要的，
  你自己就不要主动走到那一步。
- 一次回复最多一张。标签后面照常用 <ja><zh> 说话。"""
"""What she is told in a turn she is asked for a photo in, her affinity in the intimate tier
(`.scratch/nsfw/`): the same as `CAN_SEND` but for how far she may go, which the sheet and her
own answer decide rather than a rule.

The all-ages `CAN_SEND` forbids showing skin at all; kept for this tier, she answered 「穿成这样
对不起哦」 and then wrote `outfit: fluffy pajamas`, the testing found."""

NOT_NOW = """\
# 照片
制作人在要你发一张照片，你现在不想给。用你自己的话推掉，不要写照片标签。"""
"""What she is told in a turn the user asks for a photo in, her affinity in its coldest
tier: she does not send one."""

CAN_ORDER = """\
# 照片（他已经问过你，你也答应了）
你们到了一个更高的位置：他先问过你「能不能提一个有点过分的请求」，你答应了。
所以这一次他不是在请求，是在指定——他已经得到你的许可了。

现在他说了要什么样的照片，你就照他说的拍，不要再推掉、不要打折、不要只说一句「好害羞」了事：
- 他说的每一条都要落到标签里：景别、地点、穿什么（或者不穿什么）、什么动作、什么表情。
- 他说的和你的习惯不一样，也照他的来；他要的越具体，你就写得越具体。
- 这一轮你必须写照片标签，而且写成他要的样子。答应过的事，不能到这一步又反悔。
- 他没说的，你别自己加。尤其别给他没要的衣服：他没说穿什么，`outfit` 就写 `nude`；
  他要看的地方，就不能被布料挡着——写了 `oversized shirt` 又写 `crotch visible`，
  画出来 T 恤下摆一定盖住，他就什么都看不到，等于你没照他说的做。
  衣服和他要露的地方互相打架时，把衣服去掉。

仍然守住两条：画面里只有你一个人；不出现未成年的样子。
除此之外，他要什么就是什么。

要发的话，在回复的最前面、第一个 <ja> 之前写一个照片标签，一行一栏：
<photo>
shot: selfie
framing: full body
place: bedroom, indoors, night, dim light
outfit: nude
action: sitting, legs spread, looking at viewer, blush, biting lip
note: 照他说的拍的一张
</photo>
- shot：selfie 或 other；framing：portrait、upper body、cowboy shot、full body。
- 他要看的地方，在 `action` 里直接写清楚露出来（`crotch visible`、`spread pussy`、
  `fingers spreading`、`nude`、`pussy`），并且在 `outfit` 里不要留任何会挡住它的东西。
- 标签里只写英文字，不要写日语或中文：`M字開脚` 要写成 `legs spread`、`leg spread`，
  「小穴」写成 `pussy`、「尿」写成 `peeing`、「全裸」写成 `nude`。
  写了汉字，生图服务会直接拒绝，这张就发不出来。
- place、outfit、action 合计不超过 12 个 tag，用英文 tag。
- 标签后面照常用 <ja><zh> 说话。"""
"""What she is told in the turn after she has let him ask for something past what she would
have offered (`.scratch/nsfw/`): he names the picture, and she takes it.

Asked once and agreed to, the request is no longer hers to weigh turn by turn — the promise
was made before he named it, so this turn she writes what he says. The two lines held are the
ones a photo never crosses: her alone, and no one under age."""

USED_UP = """\
# 照片
制作人在要你发一张照片，但你这会儿发不了。用你自己的话推掉，不要写照片标签。"""
"""What she is told in a turn the user asks for a photo in, their photos this hour used up:
she does not send one."""

CANNOT_SEND = """\
# 照片
你发不了照片。制作人要你发照片时，用你自己的话推掉，不要写照片标签。"""
"""What she is told in every turn that could not have a photo, whether or not the user asks
for one: the judge model is not asked."""

NOT_RECEIVED = """\
# 没发出去的照片
上文里标了 status="failed" 的照片没有发出去，制作人没收到。"""
"""What she is told in a turn whose history has a photo she sent that was not sent after
all, its tag marked `status="failed"`."""

COLDEST: Tier = TIERS[0][0]

QueuedService = Literal["image", "gpt_image"]
"""The deployer's image generation, or GPT Image: whose queue a picture waits its turn in."""


@dataclass(frozen=True)
class Eligibility:
    """What a turn that could have a photo may send: one, or, the user's photos this hour
    used up, none until `used_up_until`."""

    used_up_until: datetime | None = None


@dataclass(frozen=True)
class PhotoTurn:
    """What a turn the judge model says asks for a photo comes to: what she is told of it,
    whether a photo tag she writes is kept, and, the user's photos used up, when the user
    may ask again."""

    prompt: str
    keeps_tag: bool
    used_up_until: datetime | None = None


def photo_turn(
    asked: bool,
    tier: Tier | None,
    eligibility: Eligibility,
    promised: bool = False,
    bare: bool = False,
    after: bool = False,
    ordered: bool = False,
) -> PhotoTurn | None:
    """What a turn that could have a photo, as `eligibility` says, comes to, the user having
    `asked` for one or not, her affinity in `tier` (None where affinity is off); None if not
    asked. Used up, she cannot send one, whatever her affinity.

    `promised`: she said in her last reply that she would send him one (`.scratch/nsfw/`).
    That counts as being asked: a photo she promised and then could not send left her
    saying 「真的是最后一张了哦」 with no photo at all, which is what the testing found.
    `bare`: what she promised was to be undressed, so the tag has to say so too.
    `after`: the last turns were a scene, so this photo is what is left of it — asked for
    right afterwards, she sent `underwear, bra` and 「被要求拍给他的」, the testing found.
    `ordered`: at her highest affinity she let him ask for something past the usual, so this
    turn he names the picture and she takes it (`CAN_ORDER`) — no weighing it again."""
    if not asked and not promised and not ordered:
        return None
    if eligibility.used_up_until is not None:
        return PhotoTurn(USED_UP, keeps_tag=False, used_up_until=eligibility.used_up_until)
    if ordered:
        return PhotoTurn(CAN_ORDER, keeps_tag=True)
    if tier == COLDEST:
        return PhotoTurn(NOT_NOW, keeps_tag=False)
    if tier == NSFW_TIER:
        prompt = CAN_SEND_INTIMATE
        if after:
            prompt += (
                "\n- 你们刚做完。这一张不是换了衣服再拍的，是完了之后随手拍的那一张："
                "`outfit` 写 `nude`（或者 `nude, sweat`），头发乱、脸红、身上还有汗，"
                "身上可能留着痕迹——`sweat`、`messy hair`、`cum on thigh`、`cum on stomach`、"
                "`afterglow`、`trembling` 都可以写。\n"
                "  不要写 `underwear`、`bra` 这种穿好衣服的样子，也不要把场景写成“被要求拍一张内衣照”："
                "刚完事的身体不是那样。\n"
                "  姿势不用端正好看：躺着、侧过去、被子拉到一半、腿还张着，"
                "这些才是这个时间点该有的样子，写进 `action` 里。"
            )
        if bare:
            prompt += (
                "\n- 这一张照你自己刚才说的话写：你说过已经脱掉、说全脱了、说没得再脱了，"
                "所以 `outfit` 就写 `nude`（或者 `completely nude`），不要写 `underwear`、"
                "`bra`、`underwear lowered` 这些还留着一件的样子——"
                "你嘴上说没有了、照片里却还穿着，他会觉得你在撒谎。"
            )
        return PhotoTurn(prompt, keeps_tag=True)
    return PhotoTurn(CAN_SEND, keeps_tag=True)


@dataclass
class _Generating:
    """A photo begun: whether its reply is recorded or never will be, how it came out
    once it has (its picture, or why there is none), and whether it is settled (`settled`):
    kept as it came out, or dropped."""

    recorded: bool = False
    dropped: bool = False
    outcome: tuple[bytes | None, PhotoFailure | None] | None = None
    settled: asyncio.Event = field(default_factory=asyncio.Event)


class _Queue:
    """The pictures generating on one key at most so many at a time, those waiting their
    turn, photos ahead of moments' pictures (`aside`), each first come first served, and how
    many are generating or waiting (`pictures`)."""

    def __init__(self, room: int) -> None:
        self._room = room
        self._photos: deque[asyncio.Future[None]] = deque()
        self._aside: deque[asyncio.Future[None]] = deque()
        self.pictures = 0

    async def take(self, aside: bool) -> None:
        """Wait for room for one more picture, and take it."""
        if self._room:  # none waiting, then
            self._room -= 1
            return
        turn = asyncio.get_running_loop().create_future()
        waiting = self._aside if aside else self._photos
        waiting.append(turn)
        try:
            await turn
        except asyncio.CancelledError:
            if turn.done() and not turn.cancelled():  # its turn came as it stopped waiting
                self.give()
            elif turn in waiting:
                waiting.remove(turn)
            raise

    def give(self) -> None:
        """Give back the room one picture took: to the next waiting, if any."""
        for waiting in (self._photos, self._aside):
            while waiting:
                turn = waiting.popleft()
                if not turn.done():  # one stopped waiting may not have left yet
                    turn.set_result(None)
                    return
        self._room += 1


class Photos:
    """Every photo she sends, from her tag to the picture kept with her reply."""

    def __init__(
        self,
        store: Store,
        generator: Callable[[], ImageGenerator | None],
        activity: ActivityLog,
        usage: UsageLimiter,
        own: Callable[[ImageSettings], ImageGenerator],
        gpt: Callable[[], GptImageGenerator | None] = lambda: None,
    ) -> None:
        """`generator` says, whenever asked, the deployer's image generation in effect;
        None while there is none; `gpt`, GPT Image in effect beside it, likewise. `own`
        generates on the user's own image service its settings name, in the deployment's
        art style. Their requests are recorded in
        `activity`, each photo counted in `usage`. The server starting, any photo still
        being generated when it stopped took too long."""
        self._store = store
        self._generator = generator
        self._own = own
        self._gpt = gpt
        self._activity = activity
        self._usage = usage
        self._queues: dict[tuple[QueuedService, str, int], _Queue] = {}
        self._generating: dict[str, _Generating] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        if given_up := store.give_up_photos("timeout"):
            log.info("%s photos were being generated as the server stopped; not sent", given_up)

    def eligibility(
        self,
        db: sqlite3.Connection,
        character: Character,
        user_id: str,
        own: ImageSettings | None = None,
    ) -> Eligibility | None:
        """What a turn of the user's with her may send, bringing their `own` image
        generation if any; None if it could have no photo: she has no photo tags, or it
        brings none and there is no image generation, or the user's limit is 0. Takes none
        of the user's photos, nor checks any on their own. Read through `db`, in the body of
        a read task of the caller's."""
        if not character.photographed:
            return None
        if own is not None:
            return Eligibility()
        if self._generator() is None:
            return None
        try:
            self._usage.check(db, user_id, "photo")
        except OverLimit as e:
            return None if e.retry_at is None else Eligibility(e.retry_at)
        return Eligibility()

    def begin(
        self,
        character: Character,
        tag: str,
        user_id: str,
        own: ImageSettings | None = None,
        tier: Tier | None = None,
    ) -> str:
        """Begin the photo her `tag` says, for the user, generating on their `own` image
        generation if the turn brings it, else on the deployer's, in the turn it is begun
        in; its id. Her affinity in `tier` (None where affinity is off): in `NSFW_TIER` the
        line is lifted for it (`.scratch/nsfw/`)."""
        photo_id = uuid.uuid4().hex
        self._generating[photo_id] = _Generating()
        until = asyncio.get_running_loop().time() + TIME_LIMIT
        task = asyncio.create_task(
            self._generate(photo_id, character, tag, user_id, own, until, recording(), tier)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return photo_id

    async def recorded(self, photo_id: str) -> None:
        """Her reply is recorded with the photo, being generated: it is kept as it comes out,
        or now, if it has."""
        generating = self._generating[photo_id]
        generating.recorded = True
        if generating.outcome is not None:
            await self._keep(photo_id, *generating.outcome)

    def dropped(self, photo_id: str) -> None:
        """Her reply is never to be recorded: the photo is not kept, however it comes out."""
        generating = self._generating[photo_id]
        if generating.outcome is not None:
            self._forget(photo_id)
        else:
            generating.dropped = True

    async def came_out(self, photo_id: str, user_id: str) -> Photo | None:
        """The photo, sent or not, once it has come out and is kept with her reply, for the
        user whose it is; None if it is not kept, its reply never recorded or its
        conversation deleted meanwhile, or is not theirs."""
        generating = self._generating.get(photo_id)
        if generating is not None:
            await generating.settled.wait()
        return await self._store.photo(photo_id, user_id)

    async def _generate(
        self,
        photo_id: str,
        character: Character,
        tag: str,
        user_id: str,
        own: ImageSettings | None,
        until: float,
        turn: Recording | None,
        tier: Tier | None = None,
    ) -> None:
        """Count the photo against the user's limit, as exempt on their `own` image
        generation, and generate it by `until` (the running loop's time), its request
        recorded under `turn`; given back if not sent."""
        outcome: tuple[bytes | None, PhotoFailure | None]
        try:
            use = await self._usage.take(user_id, "photo", exempt=own is not None)
        except OverLimit:
            log.info("photo %s: the user's photos this hour were used up meanwhile", photo_id)
            outcome = None, "used_up"
        except Exception:  # never left being generated for good
            log.exception("counting photo %s failed", photo_id)
            outcome = None, "service_error"
        else:
            outcome = await self._generated(photo_id, character, tag, own, until, turn, tier)
            if outcome[0] is None:
                await use.give_back()
        generating = self._generating[photo_id]
        if generating.dropped:
            self._forget(photo_id)
        elif generating.recorded:
            await self._keep(photo_id, *outcome)
        else:
            generating.outcome = outcome

    async def _generated(
        self,
        photo_id: str,
        character: Character,
        tag: str,
        own: ImageSettings | None,
        until: float,
        turn: Recording | None,
        tier: Tier | None = None,
    ) -> tuple[bytes | None, PhotoFailure | None]:
        """The photo generated by `until`, on the user's `own` image generation if any,
        or why it was not: on their own, anything but taking too long is their key's
        failing. In `NSFW_TIER` what she wrote is read with the line lifted, and the prompts
        are the tier's own (`.scratch/nsfw/`)."""
        try:
            generator = self._generator() if own is None else self._own(own)
            if generator is None:
                raise ImageFailed("service_error", "image generation is off")
            settings = generator.settings
            adult = tier == NSFW_TIER
            read = read_tag_adult(tag) if adult else read_tag(tag)
            async with self._turn_on(
                "image", settings.api_key, settings.concurrency, until, aside=False
            ):
                with turn.current() if turn is not None else nullcontext():
                    image = await timed(
                        self._activity,
                        image_origin(settings) if own is None else OWN_IMAGE_ORIGIN,
                        generator.generate(
                            image_prompt(character, read, settings.style, adult), until
                        ),
                        read.stripped,
                    )
            return image.webp, None
        except ImageFailed as e:
            if own is None:
                log.warning("photo %s was not generated: %s", photo_id, e)
                return None, e.reason
            log.warning(
                "photo %s was not generated on the user's own key: %s", photo_id,
                masked_cause(str(e), own.api_key),
            )
            return None, "timeout" if e.reason == "timeout" else "own_key_failed"
        except TimeoutError:
            log.warning("photo %s waited its turn longer than it could; never sent", photo_id)
            return None, "timeout"
        except Exception as e:  # never left being generated for good
            if own is None:
                log.exception("generating photo %s failed", photo_id)
                return None, "service_error"
            # Not with its traceback, whose messages may repeat the user's key.
            log.error(
                "generating photo %s on the user's own key failed: %s", photo_id,
                type(e).__name__,
            )
            return None, "own_key_failed"

    async def picture(
        self,
        character: Character,
        tag: PictureTag,
        until: float,
        stripped: Sequence[Crossing] | None = None,
    ) -> bytes:
        """The moment's picture of `character` `tag` says, as kept, generated on the
        deployer's image generation by `until` (the running loop's time), waiting its turn
        behind every photo waiting; its request a service call recorded under the activity
        record current, saying what was `stripped` from it (by default what `tag` says).
        Raises ImageFailed saying why there is none, or TimeoutError if its turn never came
        in time, its request never sent."""
        generator = self._generator()
        if generator is None:
            raise ImageFailed("service_error", "image generation is off")
        settings = generator.settings
        async with self._turn_on(
            "image", settings.api_key, settings.concurrency, until, aside=True
        ):
            image = await timed(
                self._activity, image_origin(settings),
                generator.generate(picture_prompt(character, tag, settings.style), until),
                tag.stripped if stripped is None else stripped,
            )
        return image.webp

    @property
    def gpt_on(self) -> bool:
        """Whether moments' pictures no one is in are generated at GPT Image now."""
        return self._gpt() is not None

    async def gpt_picture(
        self, prompt: GptPrompt, until: float, stripped: Sequence[Crossing] = ()
    ) -> bytes:
        """A moment's picture no one is in, as kept, generated at GPT Image from `prompt` by
        `until` (the running loop's time), one at a time, waiting its turn apart from the
        deployer's image generation, photos and pictures; its request a service call
        recorded under the activity record current, saying what was `stripped` from it.
        Raises ImageFailed saying why there is none, or TimeoutError if its turn never came
        in time, its request never sent."""
        generator = self._gpt()
        if generator is None:
            raise ImageFailed("service_error", "GPT Image is off")
        settings = generator.settings
        async with self._turn_on("gpt_image", settings.api_key, 1, until, aside=True):
            image = await timed(
                self._activity, image_origin(settings), generator.generate(prompt, until),
                stripped,
            )
        return image.webp

    @asynccontextmanager
    async def _turn_on(
        self, service: QueuedService, key: str, at_a_time: int, until: float, aside: bool
    ) -> AsyncIterator[None]:
        """Wait, first come first served, for the image `service` to have room for one more
        picture on `key`, `at_a_time` generating at most, a moment's picture (`aside`)
        behind every photo waiting; raises TimeoutError if there is none by `until` (the
        running loop's time). Those on the key at another number, or at another service,
        wait apart."""
        queue = self._queues.setdefault((service, key, at_a_time), _Queue(at_a_time))
        queue.pictures += 1
        try:
            async with asyncio.timeout_at(until):
                await queue.take(aside)
            try:
                if asyncio.get_running_loop().time() >= until:  # its turn came too late to send
                    raise TimeoutError
                yield
            finally:
                queue.give()
        finally:
            queue.pictures -= 1
            if not queue.pictures:
                del self._queues[service, key, at_a_time]

    async def _keep(
        self, photo_id: str, image: bytes | None, reason: PhotoFailure | None
    ) -> None:
        try:
            if not await self._store.finish_photo(photo_id, image, reason):
                log.info("photo %s came out after its reply was deleted; not kept", photo_id)
        finally:  # kept, or failed to be: none waits on it for good
            self._forget(photo_id)

    def _forget(self, photo_id: str) -> None:
        """The photo is settled: kept, or dropped."""
        self._generating.pop(photo_id).settled.set()

    async def aclose(self) -> None:
        """Stop generating: the server is shutting down."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for generating in self._generating.values():  # none waits on them for good
            generating.settled.set()
