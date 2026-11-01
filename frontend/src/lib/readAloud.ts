// Her words read aloud on the conversation page (GLOSSARY.md「朗读」): voiced on the server each time
// the user asks, kept here in memory for as long as the tab lives, the last `KEPT` of them, so that one
// heard again plays at once. Nothing is kept on the device beyond that: a refresh forgets them all.
//
// One plays at a time, through one <audio> element (`elementPlayer`): media, so the iPhone's silent switch
// leaves it sounding, as Web Audio would not. It is unlocked inside the user's click (`Player.unlock`),
// for Safari to let it play once the audio comes back from the server. The waveform is worked out from
// the audio decoded apart (`decodeVoiced`).

import { copy } from "@/i18n";
import { ApiError } from "@/lib/api";
import { toFailure, type Failure } from "@/lib/failure";

/** How many of her lines are kept voiced at most; the one heard longest ago goes first. */
export const KEPT = 30;

/** How many bars her line's waveform is drawn with. */
export const BARS = 28;

/** Which of her lines: a reply of hers, or a reach-out, in a conversation. */
export type Said = { conversationId: string; kind: "reply" | "reach_out"; id: number };

/** Her line as read aloud: being voiced; voiced, with its waveform (`peaks`, each 0–1) and length in
 * seconds, playing or not; or not voiced, and why, with when the user may read aloud again (ISO) if
 * this hour's read-alouds are used up. */
export type ReadAloudState =
  | { status: "voicing" }
  | { status: "ready"; peaks: number[]; duration: number; playing: boolean }
  | { status: "failed"; failure: Failure; retryAt: string | null };

/** Plays one line at a time. */
export interface Player {
  /** Called inside the user's click, before anything is awaited: lets it play later, once the audio is in. */
  unlock(): void;
  /** Plays `url` from `from` seconds; rejects if the browser will not. */
  play(url: string, from: number): Promise<void>;
  pause(): void;
  /** How far, in seconds, what it plays has got. */
  position(): number;
  /** `listener` is called each time what it plays comes to its end. */
  onEnded(listener: () => void): void;
}

export type ReadAloudPorts = {
  /** Her line voiced, as mp3; throws as the API does when it is not. */
  voice: (said: Said) => Promise<ArrayBuffer>;
  /** Her line's waveform and length, from its audio. */
  decode: (audio: ArrayBuffer) => Promise<{ peaks: number[]; duration: number }>;
  player: Player;
  /** An address for `audio` to be played from, and letting it go. */
  keep: (audio: ArrayBuffer) => string;
  release: (url: string) => void;
};

type Kept = { state: ReadAloudState; said: Said; url: string | null; position: number };

/** The key her line is kept by. */
export function readAloudKey(said: Said): string {
  return `${said.conversationId}/${said.kind}/${said.id}`;
}

/** Which of her lines a conversation log's entry is, by its key: a recorded reply (`m…`) or reach-out
 * (`r…`); null for anything else, a reply still under way among them. */
export function saidOf(conversationId: string, entryKey: string): Said | null {
  const match = /^([mr])(\d+)$/.exec(entryKey);
  if (!match) return null;
  return { conversationId, kind: match[1] === "m" ? "reply" : "reach_out", id: Number(match[2]) };
}

export class ReadAloud {
  private readonly kept = new Map<string, Kept>();
  private readonly listeners = new Set<() => void>();
  /** The line playing, or to play once it is voiced: the last one asked for. */
  private wanted: string | null = null;

  constructor(private readonly ports: ReadAloudPorts) {
    ports.player.onEnded(() => {
      const key = this.wanted;
      const kept = key ? this.kept.get(key) : undefined;
      if (!key || kept?.state.status !== "ready") return;
      kept.position = 0;
      this.wanted = null;
      this.set(key, { ...kept.state, playing: false });
    });
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Her line as read aloud so far; undefined if it has not been asked for, or was let go. */
  state(key: string): ReadAloudState | undefined {
    return this.kept.get(key)?.state;
  }

  /** How far, in seconds, her line has been played: where it plays now, or where it was paused. */
  position(key: string): number {
    const kept = this.kept.get(key);
    if (!kept) return 0;
    return this.wanted === key && kept.state.status === "ready" && kept.state.playing
      ? this.ports.player.position()
      : kept.position;
  }

  /** The user asked for her line to be read aloud (the menu item, or trying again): call inside their
   * click. Plays it from the start once voiced, stopping whatever plays; one being voiced is not asked
   * for again. */
  read(said: Said): void {
    this.ports.player.unlock();
    const key = readAloudKey(said);
    const kept = this.kept.get(key);
    if (kept?.state.status === "ready") {
      kept.position = 0;
      this.start(key);
      return;
    }
    this.stop();
    this.wanted = key;
    if (kept?.state.status === "voicing") return;
    this.put(key, { state: { status: "voicing" }, said, url: null, position: 0 });
    void this.voice(key, said);
  }

  /** Plays her voiced line from where it was paused, or pauses it: its play key. Call inside the click. */
  toggle(key: string): void {
    const kept = this.kept.get(key);
    if (kept?.state.status !== "ready") return;
    if (kept.state.playing) {
      this.stop();
      return;
    }
    this.ports.player.unlock();
    this.start(key);
  }

  /** Stops whatever plays, keeping where it got to; a line being voiced no longer plays once it is. */
  stop(): void {
    const key = this.wanted;
    this.wanted = null;
    const kept = key ? this.kept.get(key) : undefined;
    if (!key || kept?.state.status !== "ready" || !kept.state.playing) return;
    kept.position = this.ports.player.position();
    this.ports.player.pause();
    this.set(key, { ...kept.state, playing: false });
  }

  /** Lets go of her lines in a conversation that is gone. */
  forget(conversationId: string): void {
    for (const [key, kept] of [...this.kept]) {
      if (kept.said.conversationId !== conversationId) continue;
      if (this.wanted === key) this.stop();
      this.drop(key);
    }
    this.changed();
  }

  private async voice(key: string, said: Said): Promise<void> {
    let audio: ArrayBuffer;
    try {
      audio = await this.ports.voice(said);
    } catch (e) {
      const retryAt = e instanceof ApiError ? e.retryAt : null;
      if (this.kept.has(key)) this.set(key, { status: "failed", failure: toFailure(e), retryAt });
      if (this.wanted === key) this.wanted = null;
      return;
    }
    const shape = await this.ports.decode(audio).catch(() => ({ peaks: flat(), duration: 0 }));
    const kept = this.kept.get(key);
    if (!kept) return; // let go meanwhile
    kept.url = this.ports.keep(audio);
    this.set(key, { status: "ready", ...shape, playing: false });
    if (this.wanted === key) this.start(key);
  }

  /** Plays her voiced line `key` from where it got to, stopping any other. */
  private start(key: string): void {
    const kept = this.kept.get(key);
    if (!kept?.url || kept.state.status !== "ready") return;
    if (this.wanted !== key) this.stop();
    this.wanted = key;
    this.touch(key);
    this.set(key, { ...kept.state, playing: true });
    this.ports.player.play(kept.url, kept.position).catch(() => {
      const now = this.kept.get(key);
      if (this.wanted === key) this.wanted = null;
      if (now?.state.status === "ready") this.set(key, { ...now.state, playing: false });
    });
  }

  private put(key: string, kept: Kept): void {
    this.kept.set(key, kept);
    for (const [old, item] of this.kept) {
      if (this.kept.size <= KEPT) break;
      if (old === key || old === this.wanted || item.state.status === "voicing") continue;
      this.drop(old);
    }
    this.changed();
  }

  /** Heard again: the last to be let go. */
  private touch(key: string): void {
    const kept = this.kept.get(key);
    if (!kept) return;
    this.kept.delete(key);
    this.kept.set(key, kept);
  }

  private drop(key: string): void {
    const kept = this.kept.get(key);
    if (kept?.url) this.ports.release(kept.url);
    this.kept.delete(key);
  }

  private set(key: string, state: ReadAloudState): void {
    const kept = this.kept.get(key);
    if (!kept) return;
    kept.state = state;
    this.changed();
  }

  private changed(): void {
    for (const listener of this.listeners) listener();
  }
}

/** What the voice bar says once this hour's read-alouds are used up: when to read aloud again, by the
 * producer's time zone, to the minute and never early (within the hour, so no day). */
export function readAloudsUsedUpText(retryAt: string, timeZone: string): string {
  const at = new Date(Math.ceil(Date.parse(retryAt) / 60_000) * 60_000);
  const time = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone }).format(at);
  return copy.conversation.readAloud.usedUp(time);
}

/** The waveform of decoded audio `samples` in `bars` bars: each the loudest stretch of its part, the
 * loudest bar 1, the quietest drawn still (0.1). */
export function peaksOf(samples: Float32Array, bars = BARS): number[] {
  const size = Math.max(1, Math.floor(samples.length / bars));
  const levels = Array.from({ length: bars }, (_, bar) => {
    let sum = 0;
    const start = bar * size;
    const end = Math.min(samples.length, start + size);
    for (let i = start; i < end; i++) sum += samples[i] * samples[i];
    return end > start ? Math.sqrt(sum / (end - start)) : 0;
  });
  const loudest = Math.max(...levels);
  return levels.map((level) => (loudest > 0 ? Math.max(0.1, level / loudest) : 0.1));
}

function flat(): number[] {
  return Array.from({ length: BARS }, () => 0.5);
}

/** Her line's waveform and length, decoded apart from playing it: no user gesture is needed. */
export async function decodeVoiced(audio: ArrayBuffer): Promise<{ peaks: number[]; duration: number }> {
  const context = new OfflineAudioContext(1, 1, 44100);
  const buffer = await context.decodeAudioData(audio.slice(0));
  return { peaks: peaksOf(buffer.getChannelData(0)), duration: buffer.duration };
}

/** A moment of silence, as WAV: what the <audio> element is unlocked with. */
function silence(): Blob {
  const header = new DataView(new ArrayBuffer(44));
  const text = (at: number, s: string) => [...s].forEach((c, i) => header.setUint8(at + i, c.charCodeAt(0)));
  const samples = 8;
  text(0, "RIFF");
  header.setUint32(4, 36 + samples, true);
  text(8, "WAVEfmt ");
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true); // PCM
  header.setUint16(22, 1, true); // mono
  header.setUint32(24, 8000, true);
  header.setUint32(28, 8000, true);
  header.setUint16(32, 1, true);
  header.setUint16(34, 8, true);
  text(36, "data");
  header.setUint32(40, samples, true);
  return new Blob([header.buffer, new Uint8Array(samples).fill(128)], { type: "audio/wav" });
}

/** The page's player: one <audio> element, made the first time it is needed. */
export function elementPlayer(): Player {
  let element: HTMLAudioElement | null = null;
  let isUnlocked = false;
  let current: string | null = null;
  /** Seeks the address just set once it has a length; dropped if another is set first. */
  let seek: (() => void) | null = null;
  const ended: (() => void)[] = [];
  const audio = () => {
    if (!element) {
      element = new Audio();
      element.addEventListener("ended", () => ended.forEach((listener) => listener()));
    }
    return element;
  };
  return {
    unlock() {
      if (isUnlocked) return;
      isUnlocked = true;
      const player = audio();
      player.src = URL.createObjectURL(silence());
      current = null;
      void player.play().catch(() => {});
    },
    async play(url, from) {
      const player = audio();
      if (current !== url) {
        if (seek) player.removeEventListener("loadedmetadata", seek);
        seek = null;
        player.src = url;
        current = url;
        // A new address has no length yet to seek in: seek once it has.
        if (from > 0) {
          const at = (seek = () => {
            player.currentTime = from;
            if (seek === at) seek = null;
          });
          player.addEventListener("loadedmetadata", at, { once: true });
        }
      } else {
        player.currentTime = from;
      }
      await player.play();
    },
    pause() {
      element?.pause();
    },
    position() {
      return element?.currentTime ?? 0;
    },
    onEnded(listener) {
      ended.push(listener);
    },
  };
}
