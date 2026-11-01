"""What GPT Image is sent for a moment's picture no one is in (GLOSSARY.md「配图」「生图」): one
prompt in English sentences, put together by the server from what is at hand as she posts,
the model writing nothing more for it. The background loop and the moments eval take the
same (`gpt_picture_prompt`).

It opens with the deployment's art style for GPT Image (`GptImageSettings.style`); says what
the picture is of (scenery, food, an object) as a snapshot she posted, and who is in it: a few
passersby far off at most in scenery, no one in food or an object; where she was, the place's
name, area and what it is, marked as background alone, for GPT Image draws what it is told of
it (none where she was at none, and Tokyo not added to an area of a prefecture of its own);
what she wrote the picture shows (her note, sent now as it never was to NovelAI), to be
followed; the tags she wrote in its `place` and `action`, cleaned as they are for NovelAI; the
month and the time of day in Tokyo as she posts, and Tokyo's weather then, if known; and that
it is seen as she would have taken it, with nothing written over it. Scenery is landscape,
the others portrait, at the sizes NovelAI draws them at.
"""

from dataclasses import dataclass
from datetime import datetime

from eidolon.photo_prompt import LANDSCAPE, PORTRAIT, UNPEOPLED, Composition, PictureTag
from eidolon.place_pool import Place
from eidolon.today import TOKYO
from eidolon.weather import Kind, Weather


@dataclass(frozen=True)
class GptPrompt:
    """The prompt GPT Image is sent, and the size the picture is asked for at, width by
    height."""

    text: str
    size: tuple[int, int]


SUBJECTS: dict[Composition, str] = {"scenery": "scenery", "food": "food", "object": "an object"}
PEOPLE: dict[Composition, str] = {
    "scenery": "At most a few small, distant passersby; no one is the subject.",
    "food": "No people in the frame.",
    "object": "No people in the frame.",
}
VIEWS: dict[Composition, str] = {
    "scenery": "Seen at eye level from the ground, as if she took it herself.",
    "food": "Seen from close by, as if she took it herself.",
    "object": "Seen from close by, as if she took it herself.",
}
WEATHERS: dict[Kind, str] = {
    "clear": "clear", "cloudy": "cloudy", "overcast": "overcast", "fog": "foggy",
    "rain": "rainy", "snow": "snowy", "thunder": "thunderstorm",
}
MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)
NO_TEXT = "No added text, captions or watermarks."


def gpt_picture_prompt(
    tag: PictureTag,
    note: str,
    place: Place | None,
    at: datetime,
    weather: Weather | None,
    style: str,
) -> GptPrompt:
    """The prompt GPT Image is sent for the picture `tag` (no one in it) with her `note`, she
    at `place` (None for none), posting `at`, in Tokyo's `weather` (None for none known), in
    the art style `style`."""
    composition = tag.composition
    assert composition in UNPEOPLED
    lines = [
        style.strip(),
        f"Subject: {SUBJECTS[composition]}, a casual snapshot a young woman living in Tokyo"
        f" just posted to her social media feed. {PEOPLE[composition]}",
    ]
    if place is not None:
        area = place.area if place.nearby else f"{place.area}, Tokyo"
        lines.append(
            "Place (background information only; do not add things because of it):"
            f" {place.name}, {area} — {place.note}"
        )
    if note.strip():
        lines.append(f"What the picture shows (follow this): {note.strip()}")
    if details := list(dict.fromkeys((*tag.place, *tag.action))):
        lines.append(f"Details: {', '.join(details)}")
    local = at.astimezone(TOKYO)
    when = [MONTHS[local.month - 1], time_of_day(local.hour)]
    if weather is not None:
        when.append(WEATHERS[weather.kind])
    lines.append(f"When: {', '.join(when)}.")
    lines.append(f"{VIEWS[composition]} {NO_TEXT}")
    size = LANDSCAPE if composition == "scenery" else PORTRAIT
    return GptPrompt("\n".join(line for line in lines if line), size)


def time_of_day(hour: int) -> str:
    """The time of day the `hour` in Tokyo is, as GPT Image is told it."""
    if hour < 5:
        return "late at night"
    if hour < 11:
        return "morning"
    if hour < 14:
        return "midday"
    if hour < 17:
        return "afternoon"
    if hour < 19:
        return "evening"
    return "night"
