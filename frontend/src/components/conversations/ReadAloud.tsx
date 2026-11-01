"use client";

import type { KeyboardEvent, ReactElement, RefObject } from "react";

import { ShellLink } from "@/components/app/ShellLink";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { BARS, readAloudKey, readAloudsUsedUpText, type ReadAloud, type Said } from "@/lib/readAloud";
import { settingsHref } from "@/lib/settingsCategory";
import { cn } from "@/lib/utils";
import { PauseVoiceIcon, PlayVoiceIcon, ReadAloudIcon } from "@/theme/icons";

import { useReadAloudProgress, useReadAloudState } from "./useReadAloud";

const t = copy.conversation.readAloud;

/**
 * 她的一条话（`children`，她的气泡）上的菜单：右键、触屏长按、菜单键或 Shift+F10 打开，只有一项「朗读」
 * （GLOSSARY.md「朗读」，DESIGN.md「Chat bubbles · 朗读」）。通话中不能点。中性色，渲染到对话子树里拿到它的 `.dark`。
 * 电脑上气泡里的字照样能选；触屏上长按留给菜单。
 * 键盘：消息区里她能朗读的话只占一个 Tab 停点（`isTabStop`，最后一条），上下方向键在她的话之间移动焦点。
 */
export function ReadAloudMenu({
  readAloud,
  said,
  inCall,
  isTabStop,
  subtree,
  children,
}: {
  readAloud: ReadAloud;
  said: Said;
  inCall: boolean;
  isTabStop: boolean;
  subtree: RefObject<HTMLDivElement | null>;
  children: ReactElement;
}) {
  return (
    <ContextMenu>
      <ContextMenuTrigger
        selectable
        render={children}
        tabIndex={isTabStop ? 0 : -1}
        aria-haspopup="menu"
        data-read-aloud=""
        onKeyDown={moveAmongHerWords}
      />
      <ContextMenuContent container={subtree}>
        {/* 菜单项里的图标默认 16px、跟着菜单文字的颜色（DESIGN.md「行菜单」） */}
        <ContextMenuItem disabled={inCall} onClick={() => readAloud.read(said)}>
          <ReadAloudIcon aria-hidden />
          {t.menu}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/**
 * 她那条话下面的语音条（DESIGN.md「Chat bubbles · 朗读」）：点了「朗读」才有。合成中是转圈加一排淡的竖条；合成好了
 * 整条是播放 / 暂停键：她颜色的图标、按音频算出的波形（放过的那段是她的颜色）和时长。没合成出来时换成一行原因和「再试一次」，
 * 自带密钥没能用、或这一小时的次数用完时再加「去设置自带密钥」；次数用完的时刻按制作人的时区（`timeZone`）写。
 * 通话中播放键和「再试一次」都不能点。
 */
export function ReadAloudBar({
  readAloud,
  said,
  inCall,
  timeZone,
}: {
  readAloud: ReadAloud;
  said: Said;
  inCall: boolean;
  timeZone: string;
}) {
  const key = readAloudKey(said);
  const state = useReadAloudState(readAloud, key);
  const progress = useReadAloudProgress(readAloud, key, state);
  if (!state) return null;
  if (state.status === "failed") {
    return (
      <div role="status" className="flex flex-wrap items-baseline gap-x-2 px-1 text-meta text-muted-foreground">
        <span>{state.retryAt ? readAloudsUsedUpText(state.retryAt, timeZone) : state.failure.message}</span>
        <button
          type="button"
          disabled={inCall}
          onClick={() => readAloud.read(said)}
          className="rounded-sm font-medium text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 disabled:hover:no-underline"
        >
          {t.retry}
        </button>
        {state.failure.toOwnKeys && (
          <ShellLink href={settingsHref("own-keys")} isStandalone>
            {t.toOwnKeys}
          </ShellLink>
        )}
      </div>
    );
  }
  // 底是 --muted：她的记号色按它调到 3:1（imageColor），深色的气泡底上有几位不够。
  const pill = "flex h-9 w-fit items-center gap-2 rounded-full bg-muted pr-3.5 pl-3 max-md:h-11";
  if (state.status === "voicing") {
    return (
      <div role="status" aria-label={t.voicing} className={pill}>
        <Spinner className="size-4 text-muted-foreground" />
        <Waveform peaks={null} progress={0} />
      </div>
    );
  }
  const Icon = state.playing ? PauseVoiceIcon : PlayVoiceIcon;
  return (
    <button
      type="button"
      aria-label={state.playing ? t.pause : t.play}
      disabled={inCall}
      onClick={() => readAloud.toggle(key)}
      className={cn(pill, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50")}
    >
      <Icon aria-hidden className="size-4 fill-current text-her-mark" />
      <Waveform peaks={state.peaks} progress={progress} />
      <span className="text-meta text-muted-foreground tabular-nums">{durationText(state.duration)}</span>
    </button>
  );
}

/** 上下方向键把焦点移到上一条、下一条她能朗读的话；到头了不动。 */
function moveAmongHerWords(event: KeyboardEvent<HTMLElement>) {
  if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
  const all = [...document.querySelectorAll<HTMLElement>("[data-read-aloud]")];
  const next = all[all.indexOf(event.currentTarget) + (event.key === "ArrowUp" ? -1 : 1)];
  if (!next) return;
  event.preventDefault();
  next.focus();
  next.scrollIntoView({ block: "nearest" });
}

/** 简化的波形：一排细竖条，放过的那几根是她的颜色；还在合成时（`peaks` 为 null）一样高、淡淡地闪。 */
function Waveform({ peaks, progress }: { peaks: number[] | null; progress: number }) {
  const heights = peaks ?? Array.from({ length: BARS }, () => 0.3);
  return (
    <span aria-hidden className={cn("flex h-5 items-center gap-0.5", !peaks && "motion-safe:animate-pulse")}>
      {heights.map((height, i) => (
        <span
          key={i}
          style={{ height: `${Math.round(height * 100)}%` }}
          className={cn("w-0.5 rounded-full", peaks && (i + 0.5) / heights.length <= progress ? "bg-her-mark" : "bg-foreground/20")}
        />
      ))}
    </span>
  );
}

/** 时长，写成 0:07；长度不明时不写。 */
function durationText(seconds: number): string {
  if (!(seconds > 0)) return "";
  const whole = Math.max(1, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
