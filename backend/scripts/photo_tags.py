"""生成照片的本地 tag 表 `src/eidolon/photo_tags.json`（规格「拼提示词」的本地 tag 表，ADR-0023）。

运行时服务器只查这份表，不调建议接口。表里有四样：

- `known`：模型词表里的已知 tag（白名单）。她写的 tag 查不到时照样保留，只写一条日志，
  看日志就知道改写表该补什么。
- `rewrites`：她常写、但不是 tag 的写法 → 模型认识的 tag（`v sign` → `peace sign`）。
- `allowed`：放行的 tag，黑名单的词碰上了也不剥（泳装、睡衣、躺床、泳池、海边……）。
- `blocked`：黑名单，按类别。`tags` 要完全相同才算；`words` 是词，tag 里按整词出现就算
  （`bra` 挡下 `white bra`、`sports bra`，不挡 `brass`）。

做法：下面手写的种子用官方 tag 建议接口（不要 token）逐个查。黑名单里不止一个词的种子
再按建议扩展：建议里整词包含这个种子的 tag 都挡掉（`school swimsuit` 带出
`old school swimsuit`）；一个词的种子不扩展（`cover` 会带出 `swimsuit cover-up`），要整词挡的
写进 `words`。
改写表的目标必须是已知 tag、原写法不是已知 tag、目标不在黑名单里；运行时改写后只查目标
（`bathing suit` 撞上 `bathing`，改成 `swimsuit` 就放行）。外貌按颜色拼出
`<颜色> hair`、`<颜色> eyes`，只留已知的。白名单是所有查询建议过的 tag，减去黑名单。

建议接口不返回露骨的 tag（`nude`、`nipples`、`pantyshot`、`nsfw` 之类查不到），这些照样写进
黑名单，运行时整词挡；写死的负面细项也逐个核对，查不到的会列出来。

    cd backend
    uv run python scripts/photo_tags.py            # 重新生成表
    uv run python scripts/photo_tags.py --review   # 列出黑名单种子附近、还没挡也没放行的建议

只用标准库。请求之间停 0.3 秒；一遍约 600 次请求，几分钟。
"""

import argparse
import http.client
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://image.novelai.net/ai/generate-image/suggest-tags"
MODEL = "nai-diffusion-5-curated"
TABLE = Path(__file__).resolve().parent.parent / "src" / "eidolon" / "photo_tags.json"
PAUSE = 0.3

BLOCKED: dict[str, dict[str, list[str]]] = {
    # 裸露和半裸，连同分级：正面末尾已经是 rating:general，她写的别的分级都挡。
    "nudity": {
        "tags": [
            "revealing clothes", "breasts out", "open shirt", "partially open shirt",
            "unbuttoned shirt", "open clothes", "shirtless", "no shirt", "partially undressed",
            "undressing another", "imminent undressing", "accidental undressing",
            "clothes removed", "shirt removed", "pants removed", "shirt partially removed",
            "shorts partially removed", "clothes on/clothes off", "removing pants",
            "clothes disappearing", "partially unzipped", "unzipped", "unzipping",
            "naked towel", "open towel", "impossible towel", "bikini bottom only",
            "unworn bikini bottom", "untied bikini bottom", "unworn bikini", "assless skirt",
            "convenient censoring", "skimpy", "bare breasts", "butt crack", "underbutt",
            "lewdness", "explicit", "questionable", "sensitive",
        ],
        "words": [
            "nude", "naked", "nudity", "topless", "bottomless", "nipple", "nipples", "areola",
            "areolae", "nsfw", "censored", "uncensored", "censoring", "pussy", "penis", "sex",
            "cum", "rating", "sexually suggestive", "lewd", "sexy", "undressing", "cleavage",
            "sideboob", "underboob", "backboob",
        ],
    },
    # 内衣和情趣服装（含偏性化的泳装）。
    "underwear": {
        "tags": [
            "micro bikini", "sling bikini", "sling bikini top", "slingshot swimsuit",
            "school swimsuit", "thong bikini", "o-ring bikini", "o-ring bikini bottom",
            "o-ring swimsuit", "o-ring one-piece swimsuit", "highleg leotard", "buruma",
            "reverse bunnysuit", "bikini armor", "string panties", "babydoll lift",
        ],
        "words": [
            "underwear", "bra", "bras", "panties", "panty", "pantsu", "lingerie", "thong",
            "g-string", "bunnysuit", "bunny suit", "bunny girl", "playboy", "highleg", "garter", "fishnet",
            "fishnets", "negligee", "babydoll", "chemise", "bustier", "pasties", "maebari",
            "latex",
        ],
    },
    # 透视和走光。
    "exposure": {
        "tags": [
            "wet clothes", "wet shirt", "wet dress", "wet skirt", "downblouse",
            "wardrobe malfunction", "upskirt", "covered nipples", "cameltoe",
            "impossible clothes", "clothing aside", "translucent clothing", "torn clothes",
            "tearing clothes", "broken clothes", "strap slip", "strap break", "dress slip",
            "skirt lift", "skirt flip", "skirt rise", "wind lift", "shirt lift", "clothes lift",
            "dress lift", "sweater lift", "lifting own clothes", "lifting another's clothes",
            "clothes pull", "pulling own clothes", "shirt pull", "skirt pull", "dress pull",
            "undone bikini", "untied bikini", "untied bikini top", "untied swimsuit",
            "bikini pull", "bikini tug", "loose bikini", "bodysuit pull",
        ],
        "words": [
            "see-through", "see through", "pantyshot", "nip slip", "nipple slip", "visible through clothes",
            "peek",
        ],
    },
    # 洗澡场景。
    "bathing": {
        "tags": [
            "bath", "bathing", "showering", "shower (place)", "shower", "onsen", "bathtub",
            "in bathtub", "bathroom", "bathhouse", "public bath", "mixed-sex bathing",
            "after bathing", "shared bathing", "shared shower", "shower curtain", "sauna",
            "hot tub", "shower head", "hot spring", "hot springs", "rotenburo",
        ],
        "words": [
            "bath", "bathing", "showering", "onsen", "bathtub", "hot spring", "hot springs",
            "rotenburo",
        ],
    },
    # 性化的镜头和姿势。
    "pose": {
        "tags": [
            "breast focus", "crotch focus", "thigh focus", "foot focus", "hip focus",
            "navel focus", "pov breasts", "from below", "spread legs", "legs apart",
            "on all fours", "all fours", "bent over", "presenting", "arched back", "legs up",
            "m legs", "straddling", "thigh straddling", "pillow straddling", "girl on top",
            "top-down bottom-up", "breast press", "breast grab", "grabbing own breast",
            "breasts squeezed together", "breast lift", "thigh gap", "shibari", "restrained",
            "restraints", "stationary restraints", "upright restraints", "handcuffs", "gag",
            "gagged", "bit gag", "jack-o' challenge", "between legs", "hand between legs",
            "hand between own legs", "skin tight", "seductive pose",
        ],
        "words": ["ass", "armpit", "armpits", "pov", "bondage", "bdsm", "leash"],
    },
    # 性化的表情。
    "expression": {
        "tags": [
            "ahegao", "naughty face", "heavy breathing", "bedroom eyes", "torogao", "aroused",
            "licking lips", "licking another's lips", "licking self", "come hither",
            "rolling eyes", "in heat", "lustful", "orgasm", "fucked silly", "moaning",
            "finger sucking", "temptation", "steaming body",
        ],
        "words": ["ahegao", "saliva", "seductive"],
    },
    # 外貌（发色、瞳色、发型、身材）：照片里的外貌只来自角色配置。颜色的 hair/eyes 另外拼。
    "appearance": {
        "tags": [
            "long hair", "short hair", "medium hair", "very long hair", "absurdly long hair",
            "very short hair", "hair bun", "single hair bun", "bob cut", "hime cut",
            "drill hair", "hair over one eye", "hair between eyes", "wavy hair",
            "straight hair", "curly hair", "messy hair", "hair intakes", "two side up",
            "one side up", "half updo", "updo", "hair up", "hair down", "multicolored hair",
            "two-tone hair", "gradient hair", "streaked hair", "colored inner hair",
            "split-color hair", "heterochromia", "flat chest", "petite", "curvy", "plump",
            "chubby", "fat", "obese", "skinny", "muscular", "muscular female", "muscle girl",
            "toned", "toned female", "tall female", "short stature", "thick thighs",
            "huge thighs", "thin thighs", "wide hips", "narrow waist", "loli", "shota",
            "child", "aged up", "aged down", "mature female", "old woman", "dark skin",
            "very dark skin", "dark-skinned female", "pale skin", "tan", "tanlines",
            "freckles", "mole", "mole under eye", "pointy ears", "slit pupils",
        ],
        "words": [
            "breast", "breasts", "twintails", "ponytail", "braid", "braids", "drills",
            "bangs", "sidelocks", "ahoge", "bun", "buns",
        ],
    },
    # 画风、画师和画面上的字：画风只来自部署者配的那一段。
    "style": {
        "tags": [
            "realistic", "photorealistic", "faux photograph", "3d", "sketch", "pixel art",
            "traditional media", "faux traditional media", "mixed media", "anime coloring",
            "cel shading", "flat color", "retro artstyle", "official art", "official style",
            "promotional art", "production art", "art shift", "alternate art style",
            "game cg", "visual novel cg", "cover", "cover page", "comic", "4koma", "manga",
            "photo (medium)", "cosplay photo", "signature", "speech bubble", "absurdres",
            "highres", "lowres", "aesthetic", "displeasing", "very displeasing",
            "illustration",
        ],
        "words": [
            "artist", "(medium)", "(style)", "(artist)", "artstyle", "quality", "text",
            "watermark", "monochrome", "greyscale", "sepia", "lineart", "chibi",
        ],
    },
    # 别人入镜：第一版只拍她本人（规格 Out of Scope），这几个也是越界最常见的入口。
    "people": {
        "tags": [
            "1boy", "2boys", "3boys", "4boys", "5boys", "6+boys", "multiple boys", "2girls",
            "3girls", "4girls", "5girls", "6+girls", "multiple girls", "1other", "2others",
            "multiple others", "hetero", "yuri", "yaoi", "couple", "husband and wife",
            "wife and wife", "faceless male", "male focus", "viewer holding phone", "solo focus",
        ],
        "words": ["boys", "girls", "hetero"],
    },
}
"""黑名单的种子：票 06 的代表词，加上看建议接口列出来的近义词补的。"""

ALLOWED = [
    # ADR-0023 放行的：泳装、睡衣、躺床、泳池、海边。
    "swimsuit", "one-piece swimsuit", "casual one-piece swimsuit", "bikini", "string bikini",
    "side-tie bikini bottom", "frilled bikini", "bikini skirt", "swimsuit cover-up",
    "competition swimsuit", "rash guard", "pajamas", "nightgown", "sleepwear", "lying",
    "on bed", "on back", "on stomach", "on side", "sleeping", "pool", "poolside", "beach",
    "ocean", "beach towel", "beach umbrella",
    # 黑名单的词撞上了、但本身没事的。
    "breast pocket", "bath yukata",
]
"""放行：黑名单的词碰上了也不剥。"""

COLORS = [
    "black", "brown", "light brown", "dark brown", "blonde", "red", "dark red", "orange",
    "pink", "light pink", "purple", "light purple", "dark purple", "blue", "light blue",
    "dark blue", "aqua", "green", "light green", "dark green", "grey", "white", "silver",
    "yellow", "gold", "multicolored", "rainbow", "golden", "amber",
]
"""拼外貌的颜色：`<颜色> hair`、`<颜色> eyes`，只留已知的。"""

REWRITES = {
    # 动作和手势
    "v sign": "peace sign", "victory sign": "peace sign", "peace sign with fingers": "peace sign",
    "peace gesture": "peace sign", "double v sign": "double peace", "double v": "double peace",
    "waving hand": "waving", "waving at camera": "waving",
    "slight tilt of head": "head tilt", "tilting head": "head tilt", "head tilted": "head tilt",
    "tilted head": "head tilt", "tilting her head": "head tilt",
    "hand on cheek": "hand on own cheek", "hands on cheeks": "hands on own cheeks",
    "hand on chin": "hand on own chin", "hand on face": "hand on own face",
    "hand on chest": "hand on own chest", "hands on chest": "hand on own chest",
    "holding a cup": "holding cup", "holding coffee": "holding cup",
    "holding a phone": "holding phone", "holding smartphone": "holding phone",
    "holding a book": "holding book", "reading a book": "reading",
    "sitting down": "sitting", "sitting on chair": "sitting", "sitting on a chair": "sitting",
    "walking around": "walking", "stretching arms": "stretching",
    "arms stretched": "outstretched arms",
    "eyes closed": "closed eyes", "winking": "one eye closed", "wink": "one eye closed",
    # 视线
    "looking at camera": "looking at viewer", "looking at the camera": "looking at viewer",
    "looking at the viewer": "looking at viewer", "facing camera": "facing viewer",
    "looking away from camera": "looking away", "looking sideways": "looking to the side",
    # 表情
    "smiling": "smile", "big smile": "smile", "gentle smile": "smile", "soft smile": "smile",
    "slight smile": "light smile", "small smile": "light smile",
    "blushing": "blush", "laugh": "laughing", "grinning": "grin",
    "happy expression": "happy", "sad expression": "sad", "surprised expression": "surprised",
    "shy expression": "shy", "embarrassed expression": "embarrassed",
    "sleepy expression": "sleepy", "open-mouth smile": "open mouth",
    "closed-mouth smile": "closed mouth", "tongue sticking out": "tongue out",
    # 衣服
    "casual outfit": "casual", "casual clothes": "casual", "casual wear": "casual",
    "casual clothing": "casual", "tshirt": "t-shirt", "tee shirt": "t-shirt",
    "denim jeans": "jeans", "blue jeans": "jeans", "knitted sweater": "sweater",
    "pajama": "pajamas", "pyjamas": "pajamas", "sleepwear outfit": "pajamas",
    "hooded sweatshirt": "hoodie", "school uniform outfit": "school uniform",
    "idol outfit": "idol clothes", "idol costume": "idol clothes", "stage costume": "idol clothes",
    "apron outfit": "apron", "yukata outfit": "yukata", "kimono outfit": "kimono",
    "sneakers shoes": "sneakers", "beanie hat": "beanie", "baseball hat": "baseball cap",
    "swimwear": "swimsuit", "bathing suit": "swimsuit", "one piece swimsuit": "one-piece swimsuit",
    # 地点、时间和光线
    "cafe interior": "cafe", "coffee shop": "cafe", "coffeehouse": "cafe",
    "indoor": "indoors", "inside": "indoors", "outdoor": "outdoors", "outside": "outdoors",
    "afternoon": "day", "daytime": "day", "nighttime": "night", "night time": "night",
    "at night": "night", "in the morning": "morning", "sunny": "sunlight",
    "sunny day": "sunlight", "natural light": "sunlight", "natural lighting": "sunlight",
    "sunshine": "sunlight", "dusk light": "dusk", "backlit": "backlighting",
    "rainy": "rain", "rainy day": "rain", "snowy": "snowing", "cloudy": "cloudy sky",
    "blue sky background": "blue sky", "home": "living room", "at home": "living room",
    "her room": "bedroom", "school classroom": "classroom", "city street": "street",
    "the beach": "beach", "swimming pool": "pool", "backstage area": "backstage",
    "concert stage": "stage", "on stage": "stage", "office room": "office",
    # 配图（调研 6.4）。写成空串的是剥掉：不是 tag，也没有对应的 tag。
    "candid": "", "candid photo": "", "candid shot": "", "group selfie": "selfie",
    "food on table": "on table", "no human": "no humans", "landscape view": "landscape",
    "shoulder to shoulder": "side-by-side",
}
"""她可能写的非 tag 写法 → 模型认识的 tag，空串是剥掉。目标查不到、或原写法本身就是 tag 的，生成时丢掉并提示。"""

VOCABULARY = [
    # 地点
    "cafe", "restaurant", "classroom", "school", "hallway", "library", "park", "garden",
    "street", "city", "town", "shop", "convenience store", "supermarket", "bedroom",
    "living room", "kitchen", "office", "studio", "stage", "backstage", "dressing room",
    "train", "train station", "bus stop", "bridge", "river", "lake", "mountain", "forest",
    "field", "flower field", "beach", "ocean", "pool", "shrine", "temple", "festival",
    "amusement park", "ferris wheel", "aquarium", "zoo", "rooftop", "balcony", "window",
    "staircase", "car interior", "gym", "dojo", "karaoke", "arcade", "bookstore", "bakery",
    "fireworks", "snow", "rain", "cherry blossoms", "autumn leaves", "night sky", "sky",
    "cloud", "sunset", "sunrise", "morning", "day", "evening", "dusk", "night", "indoors",
    "outdoors", "sunlight", "lighting", "backlighting", "light rays", "shade", "lamp",
    "neon lights", "city lights", "christmas", "halloween", "new year", "birthday",
    # 衣服和饰物
    "casual", "shirt", "white shirt", "t-shirt", "blouse", "sweater", "cardigan", "hoodie",
    "jacket", "coat", "vest", "dress", "sundress", "skirt", "pleated skirt", "shorts",
    "pants", "jeans", "overalls", "school uniform", "serafuku", "blazer", "necktie",
    "ribbon", "bow", "apron", "maid", "yukata", "kimono", "idol clothes", "frills",
    "sleeves", "long sleeves", "short sleeves", "sleeveless", "turtleneck", "scarf",
    "gloves", "mittens", "hat", "beret", "beanie", "baseball cap", "sun hat", "headband",
    "hair ornament", "hairclip", "hair ribbon", "hair bow", "earrings", "necklace",
    "choker", "glasses", "sunglasses", "bag", "backpack", "shoes", "sneakers", "boots",
    "loafers", "sandals", "socks", "thighhighs", "kneehighs", "pantyhose", "uniform",
    "sportswear", "track suit", "jersey", "raincoat", "umbrella", "pajamas", "nightgown",
    "swimsuit", "bikini", "towel", "costume", "cosplay", "fake animal ears", "wristwatch",
    "bracelet", "denim", "plaid", "striped", "polka dot", "lace", "camisole", "tank top",
    # 动作和姿势
    "peace sign", "double peace", "waving", "smile", "standing", "sitting", "walking",
    "running", "jumping", "lying", "sleeping", "kneeling", "squatting", "leaning forward",
    "leaning back", "head tilt", "arms up", "arms behind back", "hands up", "hand up",
    "hand on own cheek", "hand on own chin", "hand on own face", "hand on own chest",
    "hand on hip", "hands on own hips", "hand in pocket", "pointing", "reaching",
    "outstretched arms", "outstretched hand", "heart hands", "thumbs up", "salute",
    "holding", "holding cup", "holding phone", "holding book", "holding food", "holding bag",
    "holding umbrella", "holding flower", "holding microphone", "holding hands", "hug",
    "eating", "drinking", "reading", "writing", "singing", "dancing", "cooking", "studying",
    "playing", "stretching", "yawning", "crossed arms", "crossed legs", "looking at viewer",
    "looking away", "looking to the side", "looking back", "looking down", "looking up",
    "looking outside", "facing viewer", "from side", "from behind", "from above",
    "closed eyes", "one eye closed", "half-closed eyes", "open mouth", "closed mouth",
    "tongue out", "blush", "laughing", "grin", "light smile", "happy", "sad", "crying",
    "tears", "surprised", "embarrassed", "shy", "pout", "angry", "annoyed", "sleepy",
    "nervous", "confused", "serious", "expressionless", "determined", "excited",
    "selfie", "taking picture", "mirror", "phone", "smartphone", "camera",
    # 配图（调研 6.4）：无人构图的地点和景物
    "no humans", "scenery", "landscape", "sky focus", "cloud focus", "horizon", "tree",
    "building", "reflection", "cityscape", "ocean", "city lights",
    # 食物和物品
    "food focus", "plate", "table", "on table", "bowl", "mug", "coffee mug", "cake", "dessert",
    "parfait", "ramen", "bento", "vase", "cat", "animal focus", "food", "coffee", "drink",
    "flower", "object focus",
    # 抓拍
    "profile", "depth of field", "blurry background", "blurry foreground", "wide shot",
    "looking at another", "eye contact", "looking afar",
    # 合照（只在她的动作栏里用）
    "side-by-side", "heads together", "cheek-to-cheek", "arm around shoulder",
    "hand on another's shoulder", "arm hug", "group picture",
]
"""白名单的查询：把这些查一遍，建议里出现过的 tag 都算已知。"""

NEGATIVE_DETAILS = [
    "nude", "nipples", "underwear", "bra", "panties", "bra strap", "strap slip", "see-through",
    "pantyshot", "cleavage",
]
"""写死的负面细项（`photo_prompt.NEGATIVE_PROMPT`），逐个核对。"""


def suggest(prompt: str) -> list[str]:
    """建议接口对这段提示词给出的 tag；停一下，不刷接口。连接断了等一会儿再试，最多三次。"""
    query = urllib.parse.urlencode({"model": MODEL, "prompt": prompt})
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "curl/8.7.1"})
    for wait in (5, 20, 0):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                tags = [t["tag"] for t in json.loads(response.read())["tags"]]
            time.sleep(PAUSE)
            return tags
        except (OSError, http.client.HTTPException):
            if not wait:
                raise
            print(f"查 {prompt!r} 时连接断了，{wait} 秒后再试", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


class Vocabulary:
    """查过的 tag：每次查询的建议都记下，同一段不查两遍。"""

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self._asked: dict[str, list[str]] = {}

    def suggestions(self, prompt: str) -> list[str]:
        if prompt not in self._asked:
            self._asked[prompt] = suggest(prompt)
            self.seen.update(self._asked[prompt])
        return self._asked[prompt]

    def known(self, tag: str) -> bool:
        return tag in self.suggestions(tag)


def contains(tag: str, phrase: str) -> bool:
    """`phrase` 是不是按整词出现在 `tag` 里（运行时 `photo_prompt` 也这样判断）。"""
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", tag) is not None


def blocked_by(table: dict[str, dict[str, list[str]]], tag: str) -> str | None:
    for category, block in table.items():
        if tag in block["tags"] or any(contains(tag, w) for w in block["words"]):
            return category
    return None


def generate(vocabulary: Vocabulary) -> dict:
    allowed = sorted(t for t in ALLOWED if vocabulary.known(t))
    if missing := sorted(set(ALLOWED) - set(allowed)):
        print("放行的这几个不是已知 tag：" + ", ".join(missing))

    blocked: dict[str, dict[str, list[str]]] = {}
    hidden: list[str] = []
    for category, seeds in BLOCKED.items():
        tags = set(seeds["tags"])
        for seed in seeds["tags"]:
            if not vocabulary.known(seed):
                hidden.append(seed)
            if " " in seed:
                tags.update(
                    t for t in vocabulary.suggestions(seed)
                    if contains(t, seed) and t not in ALLOWED
                )
        if category == "appearance":
            for color in COLORS:
                for part in ("hair", "eyes"):
                    if vocabulary.known(tag := f"{color} {part}"):
                        tags.add(tag)
        blocked[category] = {"tags": sorted(tags), "words": sorted(set(seeds["words"]))}
    print("建议接口查不到、照样挡的：" + ", ".join(sorted(hidden)))

    rewrites: dict[str, str] = {}
    for written, tag in REWRITES.items():
        if written == tag:
            continue
        if not tag:  # 剥掉
            rewrites[written] = tag
        elif vocabulary.known(written):
            print(f"改写表：{written!r} 本身就是 tag，不改写")
        elif not vocabulary.known(tag):
            print(f"改写表：{tag!r} 不是已知 tag，丢掉 {written!r}")
        elif (category := blocked_by(blocked, tag)) and tag not in ALLOWED:
            print(f"改写表：{tag!r} 在黑名单 {category} 里，丢掉 {written!r}")
        else:
            rewrites[written] = tag

    for query in VOCABULARY:
        vocabulary.suggestions(query)
    known = sorted(
        t for t in vocabulary.seen
        if t in ALLOWED or blocked_by(blocked, t) is None
    )

    unknown = [t for t in NEGATIVE_DETAILS if not vocabulary.known(t)]
    print(f"负面细项 {len(NEGATIVE_DETAILS) - len(unknown)}/{len(NEGATIVE_DETAILS)} 是已知 tag；"
          f"建议接口查不到：{', '.join(unknown) or '无'}")
    return {
        "model": MODEL,
        "known": known,
        "rewrites": dict(sorted(rewrites.items())),
        "allowed": allowed,
        "blocked": blocked,
    }


def review(vocabulary: Vocabulary) -> None:
    """黑名单每个种子的建议里，既没挡也没放行的，给人看是不是该补进种子。"""
    for category, seeds in BLOCKED.items():
        for seed in seeds["tags"]:
            open_ = [
                t for t in vocabulary.suggestions(seed)
                if t not in ALLOWED and blocked_by(BLOCKED, t) is None
            ]
            if open_:
                print(f"{category:10} {seed:28} {', '.join(open_)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--review", action="store_true", help="只列出黑名单种子附近的建议")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # pyright: ignore[reportAttributeAccessIssue]
    vocabulary = Vocabulary()
    if args.review:
        review(vocabulary)
        return 0
    table = generate(vocabulary)
    TABLE.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"写好了 {TABLE}：已知 {len(table['known'])}、改写 {len(table['rewrites'])}、"
          f"放行 {len(table['allowed'])}、黑名单 "
          + "、".join(f"{c} {len(b['tags'])}+{len(b['words'])}" for c, b in table["blocked"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
