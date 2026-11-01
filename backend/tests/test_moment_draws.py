"""The draws behind moments (GLOSSARY.md「朋友圈」), given what they go by and the numbers
drawn (`FakeRandom`, each below 1000): the day's plan, of who posts and when in Tokyo, and her
everyday moment's seeds, her places, her circle, when her circle shows, whether her
moment has a picture, and when she replies to the producer's comment."""

from datetime import date, datetime, time

import pytest

from eidolon.characters import Fact
from eidolon.moment_draws import (
    Eligible,
    Planned,
    draw_circle,
    draw_compositions,
    draw_places,
    draw_seeds,
    draw_reply,
    draw_shown,
    plan_day,
)
from eidolon.place_pool import Category, Place
from eidolon.schedule import done_at
from eidolon.today import TOKYO, tokyo_date
from tests.fakes import FakeRandom

DAY = date(2026, 10, 19)
MIDNIGHT = datetime.combine(DAY, time(), TOKYO)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), TOKYO)


def test_each_is_drawn_for_by_her_tier_and_given_a_time_in_a_part_of_the_day_by_its_weight():
    """Intimate 80%, close 50%, trust 25%. The parts weigh 2, 2, 4 and 1 of 9: the morning
    from 0, lunch from 2/9, after work from 4/9, late at night from 8/9 of the draw."""
    eligible = [Eligible("mano", "intimate", False), Eligible("kogane", "close", False),
                Eligible("hiori", "trust", False)]
    random = FakeRandom(
        799, 500, 249,  # posts, doesn't, posts
        0, 500,  # the morning, 08:00
        900, 0,  # late at night, 00:00
    )

    planned = plan_day(eligible, DAY, MIDNIGHT, 3, random)

    assert planned == [Planned("hiori", at(0), False), Planned("mano", at(8), False)]


def test_on_her_birthday_she_posts_and_over_the_day_birthdays_are_kept_first():
    eligible = [Eligible("mano", "trust", False), Eligible("kogane", "trust", True),
                Eligible("hiori", "intimate", False)]
    random = FakeRandom(
        0, 0,  # Mano and Hiori post; Kogane is not drawn for
        600,  # of Mano and Hiori, the second
        500, 0,  # Kogane after work, 18:00
        500, 0,  # Hiori after work, an hour after her: 19:00
    )

    planned = plan_day(eligible, DAY, MIDNIGHT, 2, random)

    assert planned == [Planned("kogane", at(18), True), Planned("hiori", at(19), False)]


def test_only_what_is_left_of_the_day_and_none_without_an_hour_apart():
    """Planned at 23:30, only the half hour after work is left; the second has nowhere to go
    an hour apart from the first, and posts nothing."""
    eligible = [Eligible("mano", "intimate", False), Eligible("kogane", "intimate", False)]
    random = FakeRandom(0, 0, 0, 500)

    planned = plan_day(eligible, DAY, at(23, 30), 3, random)

    assert planned == [Planned("mano", at(23, 45), False)]


def test_her_seeds_are_drawn_from_her_facts_but_those_of_the_people_she_knows():
    facts = [
        Fact("档案 / 基本信息", "a"), Fact("人物关系 / 風野灯織", "b"), Fact("档案 / 兴趣", "c"),
        Fact(None, "d"), Fact("人物关系", "e"), Fact("日常 / 鸽子", "f"),
    ]

    seeds = draw_seeds(facts, FakeRandom(999, 0, 500))

    assert [s.text for s in seeds] == ["f", "a", "d"]


def place(id: str, category: Category = "park", **fields) -> Place:
    return Place(id, f"{id}の名", "渋谷区", 35.6, 139.7, category, "说明", date(2026, 10, 1),
                 **fields)


def test_her_places_are_drawn_by_weight_her_liked_kinds_and_holy_sites_weighing_more():
    """A place weighs 1, one of a kind she likes 3, her holy site 4; each drawn is out of
    the next draw."""
    places = [place("a"), place("b", "cafe"), place("c", idols=("mano",), source="卡"),
              place("d"), place("e"), place("f")]
    likes = ("cafe",)
    random = FakeRandom(
        500,  # of a 1, b 3, c 4, d e f 1: 12; 6 of them falls in c (4–8)
        0,  # a
        999,  # the last, f
        250,  # of b 3, d 1, e 1: 5; 1.25 in b
    )

    drawn = draw_places(places, "mano", likes, (), at(12), (), random)

    assert [p.id for p in drawn] == ["c", "a", "f", "b"]


def test_only_places_of_the_season_and_the_slot_and_none_used_within_30_days():
    """October is autumn; 12:00 the afternoon."""
    places = [
        place("spring", seasons=("spring",)), place("autumn", seasons=("autumn", "winter")),
        place("evening", slots=("evening",)), place("afternoon", slots=("afternoon",)),
        place("used"), place("any"),
    ]

    drawn = draw_places(places, "mano", None, (), at(12), ("used",), FakeRandom(0, 0, 0))

    assert [p.id for p in drawn] == ["autumn", "afternoon", "any"]  # fewer than 4: as many


def test_late_at_night_no_place_with_slots():
    places = [place("evening", slots=("morning", "afternoon", "evening")), place("any")]

    assert [p.id for p in draw_places(places, "mano", None, (), at(1), (), FakeRandom(0))] == ["any"]


def test_a_venue_only_on_the_day_of_her_live_there_and_then_first():
    places = [place("a"), place("arena", "venue", venues=("さいたまスーパーアリーナ",)),
              place("hall", "venue")]

    on_none = draw_places(places, "mano", None, (), at(12), (), FakeRandom(0))
    on_her_live = draw_places(
        places, "mano", None, ("さいたまスーパーアリーナ",), at(12), (), FakeRandom(0)
    )

    assert [p.id for p in on_none] == ["a"]
    assert [p.id for p in on_her_live] == ["arena", "a"]


def test_her_work_moment_is_half_an_hour_to_two_hours_after_her_last_job_of_the_day_is_done():
    """Her jobs done at 13:00, her last; drawn from 13:30 to 15:00, 500 of 1000 its middle."""
    eligible = [Eligible("mano", "trust", False, last_done=at(13))]

    planned = plan_day(eligible, DAY, MIDNIGHT, 3, FakeRandom(0, 500))

    assert planned == [Planned("mano", at(14, 15), False, "work")]


def test_an_everyday_moment_is_an_hour_apart_from_a_work_moment():
    """Mano's at 19:00; Kogane's after work, from 18:00, not before 20:00."""
    eligible = [Eligible("mano", "trust", False, last_done=at(18, 30)),
                Eligible("kogane", "intimate", False)]
    random = FakeRandom(
        0, 0,  # both post
        0,  # Mano at 19:00
        500, 0,  # Kogane after work, as early as she may
    )

    planned = plan_day(eligible, DAY, MIDNIGHT, 3, random)

    assert planned == [Planned("mano", at(19), False, "work"), Planned("kogane", at(20), False)]


def test_planned_late_her_work_moment_is_in_what_is_left_of_its_time_or_of_her_everyday():
    """Planned at 15:00: done at 14:00, from 15:00 to 16:00 is left; done at 9:00, none is,
    and her everyday moment is after work, from 18:00."""
    left = plan_day([Eligible("mano", "trust", False, last_done=at(14))], DAY, at(15), 3,
                    FakeRandom(0, 500))
    over = plan_day([Eligible("mano", "trust", False, last_done=at(9))], DAY, at(15), 3,
                    FakeRandom(0, 0, 0))

    assert left == [Planned("mano", at(15, 30), False, "work")]
    assert over == [Planned("mano", at(18), False)]


@pytest.mark.parametrize(
    ("timezone", "slot", "done", "day"),
    [
        ("Asia/Shanghai", 2, at(1, day=date(2026, 10, 20)), date(2026, 10, 20)),
        ("Asia/Tokyo", 2, at(0, day=date(2026, 10, 20)), date(2026, 10, 20)),
        ("America/Los_Angeles", 0, at(4, day=date(2026, 10, 20)), date(2026, 10, 20)),
    ],
)
def test_a_job_is_of_the_day_in_tokyo_it_is_done_on(
    timezone: str, slot: int, done: datetime, day: date
):
    """Monday's evening in Shanghai is done at 01:00 on Tuesday in Tokyo; in Tokyo, at
    midnight, Tuesday's; Monday's morning in Los Angeles, at 12:00 there, at 04:00 on
    Tuesday in Tokyo."""
    at_ = done_at(DAY, 0, slot, 1, timezone)

    assert (at_, tokyo_date(at_)) == (done, day)


def test_her_circle_is_drawn_her_unit_mates_weighing_most_then_those_she_knows():
    """A unit mate weighs 3, one with a section of her facts 1; one of another unit only
    now and then; each drawn is out of the next draw."""
    random = FakeRandom(
        0,  # 4 of 4–6
        999,  # none of another unit
        500,  # of a 3, b 3, c d e 1: 9; 4.5 falls in b (3–6)
        0,  # a
        999,  # of c d e: the last, e
        0,  # c
    )

    circle = draw_circle(["a", "b"], ["c", "d", "e"], ["x", "y"], (), False, random)

    assert circle == ["b", "a", "e", "c"]


def test_one_of_another_unit_now_and_then_and_the_rest_of_them_where_too_few_she_knows():
    random = FakeRandom(
        999,  # 6 of 4–6
        249,  # one of another unit
        300,  # y of x, y, z, w
        0,  # a, the only one she knows
        0, 0, 0,  # x, z, w, as many as are left
    )

    circle = draw_circle(["a"], [], ["x", "y", "z", "w"], (), False, random)

    assert circle == ["y", "a", "x", "z", "w"]


def test_one_she_knows_whose_birthday_it_is_is_in_her_circle_but_one_of_another_unit_not():
    random = FakeRandom(0, 999, 0, 0, 0)  # 4; none of another unit; a, b, d

    circle = draw_circle(["a", "b"], ["c", "d"], ["x"], {"c", "x"}, False, random)

    assert circle == ["c", "a", "b", "d"]


def test_on_her_birthday_her_circle_is_8_to_10():
    others = [f"o{i}" for i in range(9)]
    random = FakeRandom(999, 999, *[0] * 10)  # 10 of 8–10; none of another unit; in order

    circle = draw_circle(["a", "b"], ["c"], others, (), True, random)

    assert circle == ["a", "b", "c", *others[:7]]


def test_likes_show_5_minutes_to_3_hours_after_the_moment_and_comments_15_minutes_to_6_hours_in_order():
    """Each like on its own; the comments' times drawn each, then given them in order."""
    posted = at(7)
    random = FakeRandom(
        0, 400,  # likes: 5 minutes, 5 + 175 × 0.4 = 75 minutes
        600, 0, 200,  # comments: 15 + 345 × 0.6 = 222 minutes, 15, 15 + 69 = 84
    )

    likes, comments = draw_shown(posted, 2, 3, random)

    assert likes == [at(7, 5), at(8, 15)]
    assert comments == [at(7, 15), at(8, 24), at(10, 42)]


@pytest.mark.parametrize(
    ("drawn", "photographed", "group", "compositions"),
    [
        (666, True, False, ("scenery", "food", "object", "selfie", "posed", "candid")),
        (666, True, True, ("scenery", "food", "object", "selfie", "posed", "candid", "group")),
        (666, False, True, ("scenery", "food", "object")),
        (667, True, True, ()),
    ],
)
def test_two_thirds_of_her_moments_have_a_picture_of_her_only_where_she_has_photo_tags(
    drawn: int, photographed: bool, group: bool, compositions: tuple[str, ...]
):
    assert draw_compositions(True, photographed, FakeRandom(drawn), group) == compositions


def test_without_image_generation_none_has_a_picture_nor_is_drawn_for():
    assert draw_compositions(False, True, FakeRandom(), True) == ()


@pytest.mark.parametrize(
    ("tier", "drawn", "after"),
    [("intimate", 999, 29), ("close", 500, 37), ("trust", 0, 30)],
)
def test_she_replies_to_his_comment_the_sooner_the_closer_she_is(
    tier: str, drawn: int, after: int
):
    """Intimate within 5–30 minutes, close 15–60, trust 30–120, to the whole minute here."""
    commented = at(23, 50)

    reply = draw_reply(commented, tier, FakeRandom(drawn))  # type: ignore[arg-type]

    assert reply is not None
    assert int((reply - commented).total_seconds() // 60) == after


def test_below_trust_she_does_not_reply():
    """Cold alike; a cooldown the caller tells as None."""
    assert draw_reply(at(12), "distant", FakeRandom()) is None
