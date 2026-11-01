"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { readAloud as voice, type Account } from "@/lib/api";
import { localOwnKeys, subscribeOwnKeys } from "@/lib/localOwnKeys";
import { decodeVoiced, elementPlayer, ReadAloud, type Player, type ReadAloudState } from "@/lib/readAloud";

let player: Player | null = null;
let shared: { userId: string; readAloud: ReadAloud } | null = null;

/** 这个标签页里朗读她的话的那一个（GLOSSARY.md「朗读」）：活到标签页关掉，换页不丢，刷新就没了；
 * 换了一位用户就换一个新的（前一位的由用它的那一页停下）。 */
export function readAloudFor(userId: string): ReadAloud {
  if (shared?.userId !== userId) {
    player ??= elementPlayer();
    shared = {
      userId,
      readAloud: new ReadAloud({
        voice: (said) => voice(said, userId),
        decode: decodeVoiced,
        player,
        keep: (audio) => URL.createObjectURL(new Blob([audio], { type: "audio/mpeg" })),
        release: (url) => URL.revokeObjectURL(url),
      }),
    };
  }
  return shared.readAloud;
}

/** 她的一条话朗读到哪一步了；没点过「朗读」或已经放掉了是 undefined。 */
export function useReadAloudState(readAloud: ReadAloud, key: string): ReadAloudState | undefined {
  return useSyncExternalStore(
    readAloud.subscribe,
    () => readAloud.state(key),
    () => undefined,
  );
}

/** 这位用户能不能朗读：部署者有语音合成的 key，或者这个浏览器为这位用户存着自己的。 */
export function useCanReadAloud(userId: string, account: Account | null): boolean {
  const hasOwn = useSyncExternalStore(
    subscribeOwnKeys,
    () => localOwnKeys(userId).tts !== undefined,
    () => false,
  );
  return hasOwn || account?.deployer_tts === true;
}

/** 正在放的这一条放到了几成（0–1），每一帧跟着走；不在放时停在暂停处。 */
export function useReadAloudProgress(readAloud: ReadAloud, key: string, state: ReadAloudState | undefined): number {
  const isPlaying = state?.status === "ready" && state.playing;
  const duration = state?.status === "ready" ? state.duration : 0;
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    const measure = () => setProgress(duration > 0 ? Math.min(1, readAloud.position(key) / duration) : 0);
    measure();
    if (!isPlaying) return;
    let frame = requestAnimationFrame(function tick() {
      measure();
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [readAloud, key, isPlaying, duration]);
  return progress;
}
