import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import {
  KEPT,
  peaksOf,
  ReadAloud,
  readAloudKey,
  readAloudsUsedUpText,
  saidOf,
  type Player,
  type Said,
} from "@/lib/readAloud";

/** A player that plays nothing: says what it was told, its position set by the test. */
class FakePlayer implements Player {
  readonly calls: string[] = [];
  at = 0;
  private ended: (() => void)[] = [];

  unlock() {
    this.calls.push("unlock");
  }
  async play(url: string, from: number) {
    this.calls.push(`play ${url} from ${from}`);
  }
  pause() {
    this.calls.push("pause");
  }
  position() {
    return this.at;
  }
  onEnded(listener: () => void) {
    this.ended.push(listener);
  }
  end() {
    this.ended.forEach((listener) => listener());
  }
}

/** Her lines voiced as the test answers them, each as an audio naming it. */
function setUp() {
  const player = new FakePlayer();
  const asked: Said[] = [];
  const answers = new Map<string, { resolve: (audio: ArrayBuffer) => void; reject: (e: unknown) => void }>();
  const released: string[] = [];
  const readAloud = new ReadAloud({
    voice: (said) =>
      new Promise((resolve, reject) => {
        asked.push(said);
        answers.set(readAloudKey(said), { resolve, reject });
      }),
    decode: async () => ({ peaks: [0.5, 1], duration: 7 }),
    player,
    keep: () => `blob:${asked.length}`,
    release: (url) => released.push(url),
  });
  const voiced = async (said: Said) => {
    answers.get(readAloudKey(said))!.resolve(new ArrayBuffer(1));
    await vi.waitFor(() => expect(readAloud.state(readAloudKey(said))?.status).not.toBe("voicing"));
  };
  return { readAloud, player, asked, answers, released, voiced };
}

const one: Said = { conversationId: "c1", kind: "reply", id: 1 };
const two: Said = { conversationId: "c1", kind: "reach_out", id: 2 };

describe("ReadAloud", () => {
  it("unlocks the player in the click, then plays her line from the start once it is voiced", async () => {
    const { readAloud, player, asked, voiced } = setUp();

    readAloud.read(one);

    expect(player.calls).toEqual(["unlock"]);
    expect(readAloud.state(readAloudKey(one))).toEqual({ status: "voicing" });
    await voiced(one);
    expect(readAloud.state(readAloudKey(one))).toEqual({ status: "ready", peaks: [0.5, 1], duration: 7, playing: true });
    expect(player.calls).toEqual(["unlock", "play blob:1 from 0"]);
    readAloud.read(one); // heard again: not voiced again, played from the start
    expect(asked).toEqual([one]);
    expect(player.calls.at(-1)).toBe("play blob:1 from 0");
  });

  it("pauses and plays on where it was, and back to the start once it ends", async () => {
    const { readAloud, player, voiced } = setUp();
    const key = readAloudKey(one);
    readAloud.read(one);
    await voiced(one);

    player.at = 3;
    readAloud.toggle(key);
    expect(readAloud.state(key)).toMatchObject({ playing: false });
    expect(readAloud.position(key)).toBe(3);
    readAloud.toggle(key);
    expect(player.calls.at(-1)).toBe("play blob:1 from 3");
    player.end();

    expect(readAloud.state(key)).toMatchObject({ playing: false });
    expect(readAloud.position(key)).toBe(0);
  });

  it("plays one at a time: the last asked for, a line stopped while voiced not at all", async () => {
    const { readAloud, player, voiced } = setUp();
    readAloud.read(one);
    await voiced(one);

    readAloud.read(two);
    expect(readAloud.state(readAloudKey(one))).toMatchObject({ playing: false });
    expect(player.calls.at(-1)).toBe("pause");
    readAloud.stop(); // a call starts
    await voiced(two);

    expect(readAloud.state(readAloudKey(two))).toMatchObject({ status: "ready", playing: false });
    expect(player.calls.filter((call) => call.startsWith("play"))).toEqual(["play blob:1 from 0"]);
  });

  it("says why it was not voiced and when to read aloud again, and is asked again on trying again", async () => {
    const { readAloud, answers, asked } = setUp();
    const key = readAloudKey(one);
    readAloud.read(one);

    const retryAt = "2026-10-31T05:00:00+00:00";
    answers.get(key)!.reject(new ApiError("这一小时的朗读次数已经用完了（每小时 60 次）", 429, { retryAt }));
    await vi.waitFor(() => expect(readAloud.state(key)?.status).toBe("failed"));
    expect(readAloud.state(key)).toMatchObject({
      status: "failed",
      failure: { message: "这一小时的朗读次数已经用完了（每小时 60 次）" },
      retryAt,
    });
    readAloud.read(one);

    expect(readAloud.state(key)).toEqual({ status: "voicing" });
    expect(asked).toEqual([one, one]);
  });

  it(`keeps the last ${KEPT} heard, letting the rest go, and those of a conversation that is gone`, async () => {
    const { readAloud, released, voiced } = setUp();
    const lines = Array.from({ length: KEPT + 1 }, (_, i): Said => ({ conversationId: `c${i % 2}`, kind: "reply", id: i }));
    for (const said of lines) {
      readAloud.read(said);
      await voiced(said);
    }

    expect(readAloud.state(readAloudKey(lines[0]))).toBeUndefined();
    expect(released).toEqual(["blob:1"]);
    readAloud.forget("c1");
    expect(lines.filter((said) => readAloud.state(readAloudKey(said)) !== undefined).map((said) => said.id)).toEqual(
      lines.filter((said) => said.id > 0 && said.conversationId === "c0").map((said) => said.id),
    );
  });
});

describe("saidOf", () => {
  it("tells her recorded replies and reach-outs from what is not one", () => {
    expect(saidOf("c1", "m12")).toEqual({ conversationId: "c1", kind: "reply", id: 12 });
    expect(saidOf("c1", "r3")).toEqual({ conversationId: "c1", kind: "reach_out", id: 3 });
    expect(saidOf("c1", "new-4")).toBeNull();
  });
});

describe("readAloudsUsedUpText", () => {
  it("says when to read aloud again by the producer's time zone, to the minute and never early", () => {
    expect(readAloudsUsedUpText("2026-10-31T05:00:30+00:00", "Asia/Tokyo")).toBe(
      "这一小时的朗读次数用完了，14:01 以后可以再听",
    );
  });
});

describe("peaksOf", () => {
  it("draws each part's loudness against the loudest, the quietest still seen", () => {
    const samples = new Float32Array([0, 0, 0.5, -0.5, 1, -1]);
    expect(peaksOf(samples, 3)).toEqual([0.1, 0.5, 1]);
  });
});
