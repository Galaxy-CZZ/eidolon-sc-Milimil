import { describe, expect, it } from "vitest";

import {
  banAction,
  describeLimit,
  describeLimits,
  limitDraft,
  limitsInput,
  headerSort,
  pageOffset,
  usageRows,
  describeCount,
  type AdminUser,
  type AdminUserLimits,
} from "@/lib/adminUsers";

const USER: AdminUser = {
  id: "u1",
  name: "octo",
  sign_in_methods: [],
  created_at: "2026-10-01T00:00:00+00:00",
  last_active_at: null,
  banned: false,
  is_admin: false,
  limits: null,
  usage_24h: { turns: 0, calls: 0 },
};

describe("banAction", () => {
  it("offers to ban a user, to lift a ban, and nothing for an admin", () => {
    expect(banAction(USER)).toBe("ban");
    expect(banAction({ ...USER, banned: true })).toBe("unban");
    expect(banAction({ ...USER, is_admin: true })).toBeNull();
  });
});

describe("pageOffset", () => {
  it("skips the users of the pages before", () => {
    expect(pageOffset(1)).toBe(0);
    expect(pageOffset(3)).toBe(100);
  });
});

describe("describeLimit", () => {
  it("says what a user's own limit is: the deployment's, unlimited, own keys only, or a number", () => {
    expect(describeLimit(null)).toBe("跟随全站");
    expect(describeLimit("unlimited")).toBe("不限");
    expect(describeLimit(0)).toBe("只能用自带密钥");
    expect(describeLimit(3)).toBe("每小时 3 次");
  });
});

describe("limitDraft and limitsInput", () => {
  const followed = limitDraft(null);

  const allFollowed = { turns: followed, calls: followed, photos: followed, visits: followed, readAlouds: followed };
  const noLimits = {
    turns_per_hour: null,
    calls_per_hour: null,
    photos_per_hour: null,
    visits_per_hour: null,
    read_alouds_per_hour: null,
  };

  it("round-trips each kind of limit through the editor", () => {
    for (const limit of [null, "unlimited", 0, 5] as const) {
      const draft = limitDraft(limit);
      expect(
        limitsInput({ turns: draft, calls: limitDraft(5), photos: draft, visits: draft, readAlouds: draft }),
        String(limit),
      ).toEqual({
        input: {
          turns_per_hour: limit,
          calls_per_hour: 5,
          photos_per_hour: limit,
          visits_per_hour: limit,
          read_alouds_per_hour: limit,
        },
      });
    }
  });

  it("keeps own keys only apart from a number: 0 is never typed in", () => {
    expect(limitDraft(0)).toEqual({ choice: "own_keys", count: null });
    expect(limitsInput({ ...allFollowed, turns: { choice: "number", count: 0 }, calls: limitDraft(5) })).toEqual({
      problems: [{ field: "turns", reason: "count" }],
    });
  });

  it("saves any one of them alone, the others following the deployment", () => {
    expect(limitsInput({ ...allFollowed, photos: limitDraft(0) })).toEqual({
      input: { ...noLimits, photos_per_hour: 0 },
    });
    expect(limitsInput({ ...allFollowed, readAlouds: limitDraft("unlimited") })).toEqual({
      input: { ...noLimits, read_alouds_per_hour: "unlimited" },
    });
  });

  it("names why there is nothing to save: all follow the deployment, or a number is chosen but not given", () => {
    expect(limitsInput(allFollowed)).toEqual({
      problems: [{ field: "turns", reason: "needsOne" }],
    });
    expect(limitsInput({ ...allFollowed, turns: { choice: "number", count: null } })).toEqual({
      problems: [{ field: "turns", reason: "count" }],
    });
    const none = { choice: "number", count: null } as const;
    expect(limitsInput({ turns: none, calls: none, photos: none, visits: none, readAlouds: none })).toEqual({
      problems: [
        { field: "turns", reason: "count" },
        { field: "calls", reason: "count" },
        { field: "photos", reason: "count" },
        { field: "visits", reason: "count" },
        { field: "readAlouds", reason: "count" },
      ],
    });
  });
});

describe("describeLimits", () => {
  const limits: AdminUserLimits = {
    turns_per_hour: 5,
    calls_per_hour: null,
    photos_per_hour: null,
    visits_per_hour: null,
    read_alouds_per_hour: null,
    note: null,
    updated_at: "2026-10-11T00:00:00+00:00",
  };

  it("puts turns and calls in a line, with nothing about using the deployer's LLM", () => {
    expect(describeLimits(limits)).toBe("回合 每小时 5 次 · 通话 跟随全站");
  });

  it("adds the photos where they are set apart", () => {
    expect(describeLimits({ ...limits, photos_per_hour: 2 })).toBe("回合 每小时 5 次 · 通话 跟随全站 · 照片 每小时 2 张");
    expect(describeLimits({ ...limits, photos_per_hour: 0 })).toBe(
      "回合 每小时 5 次 · 通话 跟随全站 · 照片 只能用自带密钥",
    );
  });

  it("adds the visits and the read-alouds where they are set apart, after the photos", () => {
    expect(describeLimits({ ...limits, visits_per_hour: 2 })).toBe("回合 每小时 5 次 · 通话 跟随全站 · 光顾 每小时 2 次");
    expect(describeLimits({ ...limits, photos_per_hour: 1, visits_per_hour: "unlimited", read_alouds_per_hour: 0 })).toBe(
      "回合 每小时 5 次 · 通话 跟随全站 · 照片 每小时 1 张 · 光顾 不限 · 朗读 只能用自带密钥",
    );
  });
});

describe("headerSort", () => {
  it("sorts by a usage column, most first, and back to newest when its header is clicked again", () => {
    expect(headerSort("newest", "turns")).toBe("turns");
    expect(headerSort("turns", "calls")).toBe("calls");
    expect(headerSort("turns", "turns")).toBe("newest");
  });
});

describe("describeCount", () => {
  it("gives the total, and on whose keys when there are any", () => {
    expect(describeCount({ deployer: 0, own_keys: 0 }, "turns")).toEqual({ total: "0", split: null });
    expect(describeCount({ deployer: 3, own_keys: 2 }, "turns")).toEqual({
      total: "5",
      split: "部署者 3 · 自带密钥 2",
    });
  });

  it("splits calls by whether they counted, a call on own keys being one that brought every exempting key", () => {
    expect(describeCount({ deployer: 3, own_keys: 2 }, "calls")).toEqual({ total: "5", split: "计入限额 3 · 不计入 2" });
  });
});

describe("usageRows", () => {
  it("has a row for turns, calls and rejections, each with the three ranges", () => {
    const counted = (deployer: number, own_keys: number) => ({ deployer, own_keys });
    const range = (n: number) => ({ turns: counted(n, 0), calls: counted(0, n), rejected: counted(0, 0) });
    const rows = usageRows({ "24h": range(1), "7d": range(2), "30d": range(3) });

    expect(rows.map((row) => [row.what, row.label])).toEqual([
      ["turns", "回合"],
      ["calls", "通话"],
      ["rejected", "被拒绝"],
    ]);
    expect([rows[0]["24h"], rows[0]["7d"], rows[0]["30d"]]).toEqual([counted(1, 0), counted(2, 0), counted(3, 0)]);
    expect(rows[1]["30d"]).toEqual(counted(0, 3));
  });
});
