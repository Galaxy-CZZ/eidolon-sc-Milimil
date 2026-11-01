import { Cloud, CloudFog, CloudLightning, CloudRain, CloudSnow, CloudSun, Sun } from "lucide-react";
import { describe, expect, it } from "vitest";

import type { Moment, WeatherKind } from "@/lib/api";
import { canSendComment, metaParts, momentActions, postedText, reactions } from "@/lib/moments";

/** 本地时间的某一刻（测试不依赖所在时区）。 */
function local(day: number, hour: number, minute = 0, second = 0): Date {
  return new Date(2026, 9, day, hour, minute, second);
}

const now = local(31, 12, 0);

describe("时间线一行的时间", () => {
  it("不到 1 分钟写「刚刚」，露出在将来（钟慢了）也是", () => {
    expect(postedText(local(31, 11, 59, 30).toISOString(), now)).toBe("刚刚");
    expect(postedText(now.toISOString(), now)).toBe("刚刚");
    expect(postedText(local(31, 12, 5).toISOString(), now)).toBe("刚刚");
  });

  it("不到 1 小时写几分钟前，向下取整", () => {
    expect(postedText(local(31, 11, 59).toISOString(), now)).toBe("1 分钟前");
    expect(postedText(local(31, 11, 0, 30).toISOString(), now)).toBe("59 分钟前");
  });

  it("不到 24 小时写几小时前，跨过半夜也是", () => {
    expect(postedText(local(31, 11, 0).toISOString(), now)).toBe("1 小时前");
    expect(postedText(local(30, 12, 0, 1).toISOString(), now)).toBe("23 小时前");
    expect(postedText(local(30, 23, 0).toISOString(), local(31, 1, 0))).toBe("2 小时前");
  });

  it("再早按日历算：前一天写「昨天」，更早写几天前", () => {
    expect(postedText(local(30, 12, 0).toISOString(), now)).toBe("昨天");
    expect(postedText(local(30, 0, 0).toISOString(), now)).toBe("昨天");
    expect(postedText(local(29, 23, 0).toISOString(), now)).toBe("2 天前");
    expect(postedText(local(1, 12, 0).toISOString(), now)).toBe("30 天前");
  });
});

describe("时间线一行的 Meta", () => {
  const moment: Moment = {
    id: 1,
    character_id: "mano",
    ja: "池のボート",
    zh: "池塘的小船",
    image: null,
    place: null,
    weather: null,
    posted_at: local(31, 11, 0).toISOString(),
    likes: [],
    comments: [],
    producer_liked: false,
    producer_comment: null,
    reply: null,
  };
  const map = "https://www.openstreetmap.org/?mlat=35.6997&mlon=139.5731#map=17/35.6997/139.5731";

  it("有地名时是「时间 · 地名」，地名带地图链接", () => {
    const parts = metaParts({ ...moment, place: { name: "井の頭恩賜公園", map } }, now);
    expect(parts).toEqual([
      { kind: "time", text: "1 小时前" },
      { kind: "place", text: "井の頭恩賜公園", href: map },
    ]);
  });

  it("没有地名时只有时间，分隔点也省掉", () => {
    expect(metaParts(moment, now)).toEqual([{ kind: "time", text: "1 小时前" }]);
  });

  it("有天气时排在最后，是图标加整数气温：「时间 · 地名 · ☀ 18°」", () => {
    const parts = metaParts(
      { ...moment, place: { name: "井の頭恩賜公園", map }, weather: { kind: "clear", temperature: 18 } },
      now,
    );
    expect(parts).toEqual([
      { kind: "time", text: "1 小时前" },
      { kind: "place", text: "井の頭恩賜公園", href: map },
      { kind: "weather", text: "18°", icon: Sun, label: "晴" },
    ]);
  });

  it("没有地名、有天气时是「时间 · 天气」，零下照写负号", () => {
    expect(metaParts({ ...moment, weather: { kind: "snow", temperature: -2 } }, now)).toEqual([
      { kind: "time", text: "1 小时前" },
      { kind: "weather", text: "-2°", icon: CloudSnow, label: "雪" },
    ]);
  });

  it("有地名、没有天气时是「时间 · 地名」", () => {
    expect(metaParts({ ...moment, place: { name: "井の頭恩賜公園", map } }, now).map((p) => p.kind)).toEqual([
      "time",
      "place",
    ]);
  });

  it.each<[WeatherKind, unknown, string]>([
    ["clear", Sun, "晴"],
    ["cloudy", CloudSun, "多云"],
    ["overcast", Cloud, "阴"],
    ["fog", CloudFog, "雾"],
    ["rain", CloudRain, "雨"],
    ["snow", CloudSnow, "雪"],
    ["thunder", CloudLightning, "雷雨"],
  ])("天气「%s」用它自己的图标", (kind, icon, label) => {
    const weather = metaParts({ ...moment, weather: { kind, temperature: 10 } }, now).at(-1);
    expect(weather).toEqual({ kind: "weather", text: "10°", icon, label });
  });
});

describe("一条动态下面赞和评论的那一块", () => {
  const moment: Moment = {
    id: 1,
    character_id: "mano",
    ja: "池のボート",
    zh: "池塘的小船",
    image: null,
    place: null,
    weather: null,
    posted_at: local(31, 11, 0).toISOString(),
    likes: [],
    comments: [],
    producer_liked: false,
    producer_comment: null,
    reply: null,
  };
  const names: Record<string, string> = { hiori: "風野灯織", meguru: "八宮めぐる" };
  const nameOf = (id: string) => names[id] ?? id;
  const hiori = { character_id: "hiori", ja: "真乃、楽しそう", zh: "真乃，看起来好开心" };

  it("没人赞也没人评论时这一块不出现", () => {
    expect(reactions(moment, nameOf, "櫻木真乃")).toBeNull();
  });

  it("赞的人按先后用「，」连成一行", () => {
    expect(reactions({ ...moment, likes: ["meguru", "hiori"] }, nameOf, "櫻木真乃")).toEqual({
      likers: "八宮めぐる，風野灯織",
      comments: [],
    });
  });

  it("他赞了排在最前，写「制作人」；只有他赞时也有这一块", () => {
    expect(reactions({ ...moment, likes: ["meguru"], producer_liked: true }, nameOf, "櫻木真乃")?.likers).toBe(
      "制作人，八宮めぐる",
    );
    expect(reactions({ ...moment, producer_liked: true }, nameOf, "櫻木真乃")).toEqual({ likers: "制作人", comments: [] });
  });

  it("评论按先后，每条「名字：」打头，带日语和字幕；没人赞时没有赞的一行", () => {
    const meguru = { character_id: "meguru", ja: "わたしも行く！", zh: "我也要去！" };
    expect(reactions({ ...moment, comments: [hiori, meguru] }, nameOf, "櫻木真乃")).toEqual({
      likers: null,
      comments: [
        { kind: "idol", by: "風野灯織：", ja: hiori.ja, zh: hiori.zh },
        { kind: "idol", by: "八宮めぐる：", ja: meguru.ja, zh: meguru.zh },
      ],
    });
  });

  it("他的评论照原样写「制作人：内容」，排在偶像的评论后面，她的回复跟在后面写「她 回复 制作人：」", () => {
    const commented = {
      ...moment,
      comments: [hiori],
      producer_comment: { text: "鸽子叫什么名字？", commented_at: local(31, 11, 30).toISOString() },
    };
    expect(reactions(commented, nameOf, "櫻木真乃")?.comments).toEqual([
      { kind: "idol", by: "風野灯織：", ja: hiori.ja, zh: hiori.zh },
      { kind: "producer", by: "制作人：", text: "鸽子叫什么名字？" },
    ]);
    const replied = { ...commented, reply: { ja: "ピーちゃんです！", zh: "叫小哔！" } };
    expect(reactions(replied, nameOf, "櫻木真乃")?.comments.slice(1)).toEqual([
      { kind: "producer", by: "制作人：", text: "鸽子叫什么名字？" },
      { kind: "idol", by: "櫻木真乃 回复 制作人：", ja: "ピーちゃんです！", zh: "叫小哔！" },
    ]);
  });

  it("只有他的评论时也有这一块，没有赞的一行", () => {
    const commented = { ...moment, producer_comment: { text: "好看", commented_at: now.toISOString() } };
    expect(reactions(commented, nameOf, "櫻木真乃")?.likers).toBeNull();
  });

  it("名字取不到时写 id", () => {
    expect(reactions({ ...moment, likes: ["kogane"] }, nameOf, "櫻木真乃")?.likers).toBe("kogane");
  });
});

describe("一条动态行尾「⋯」里的几项", () => {
  const moment: Moment = {
    id: 1,
    character_id: "mano",
    ja: "池のボート",
    zh: "池塘的小船",
    image: null,
    place: null,
    weather: null,
    posted_at: local(31, 11, 0).toISOString(),
    likes: [],
    comments: [],
    producer_liked: false,
    producer_comment: null,
    reply: null,
  };
  const commented = { text: "好看", commented_at: now.toISOString() };

  it("没赞没评论时是「赞」「评论」，都能点", () => {
    expect(momentActions(moment)).toEqual([
      { action: "like", label: "赞", disabled: false },
      { action: "comment", label: "评论", disabled: false },
    ]);
  });

  it("赞过了是「取消赞」", () => {
    expect(momentActions({ ...moment, producer_liked: true })[0]).toEqual({
      action: "unlike",
      label: "取消赞",
      disabled: false,
    });
  });

  it("评论过以后「评论」不能点，另多一项「删除评论」", () => {
    expect(momentActions({ ...moment, producer_comment: commented }).slice(1)).toEqual([
      { action: "comment", label: "评论", disabled: true },
      { action: "uncomment", label: "删除评论", disabled: false },
    ]);
  });
});

describe("评论能不能发", () => {
  it("去掉首尾空白后 1 到 140 个字", () => {
    expect(canSendComment("  \n ")).toBe(false);
    expect(canSendComment("好")).toBe(true);
    expect(canSendComment(`  ${"鸽".repeat(140)}  `)).toBe(true);
    expect(canSendComment("鸽".repeat(141))).toBe(false);
  });

  it("按字数算，emoji 一个算一个字", () => {
    expect(canSendComment("🕊".repeat(140))).toBe(true);
    expect(canSendComment("🕊".repeat(141))).toBe(false);
  });
});
