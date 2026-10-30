"use client";

import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SignInButton } from "@/components/app/FailureNotice";
import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useWhileVisible } from "@/hooks/useWhileVisible";
import { copy } from "@/i18n";
import type { Character } from "@/lib/api";
import { showTime } from "@/lib/callTime";
import { arrange, dayOf, previewOf, type ListRow, type Preview } from "@/lib/conversationList";
import { createGroup, listGroups, type GroupSummary } from "@/lib/group";
import { pin, setShown, unpin } from "@/lib/listPreferences";
import { cn } from "@/lib/utils";
import { herVars } from "@/theme/herVars";
import { HideIcon, PinIcon, SearchIcon, ShowIcon, UnpinIcon, GroupCardIcon } from "@/theme/icons";

import { Announcements } from "./Announcements";
import { PreviewText } from "./PreviewText";
import { ServiceStatusButton } from "./ServiceStatusButton";
import { useDirectory, type CallInList } from "./ConversationDirectory";
import { ListFilter } from "./ListFilter";
import { useCallTime } from "./useCallTime";

const t = copy.conversationList;

/**
 * 对话列表（DESIGN.md「Conversation list」）：顶上「对话」大标题、服务状态和公告铃铛，下面一个按名字
 * 或组合找人的搜索框，右边是筛选按钮（`ListFilter`）；每位角色一行（56px 头像、名字和时间一行，最后一句一行），
 * 选中行铺中性的 bg-muted；有人被隐藏时最后一行是「已隐藏 n 位」。她有没看过的搭话时，时间前面一个她颜色的小圆点，当前对话正显示着的那位不标。显示谁、按什么顺序由 `arrange` 决定：置顶的在前，最近有过往来的在上面；隐藏的不显示，
 * 但搜索时照样能搜到，当前打开的和正在通话的始终留下。一整列不按组合分段，换位置时直接跳过去、不做动画。
 * 列表栏是实底，不在她的子树里。宽屏时在左栏，窄屏时占满一页。
 */
export function ConversationList({ selectedId }: { selectedId: string | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const { groupId: openGroupId } = useParams<{ groupId?: string }>();
  const { account, characters, latest, preferences, tidy, failure, reload, call, go, onScreen } = useDirectory();
  const now = useMinute();
  const [query, setQuery] = useState("");
  const [isFilterOpen, setFilterOpen] = useState(false);
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [making, setMaking] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);

  const loadGroups = useCallback(() => {
    listGroups().then(setGroups, () => {});
  }, []);

  useEffect(() => {
    loadGroups();
  }, [loadGroups, pathname]);

  // 群聊的新消息、预览和已读状态都跟着列表刷新：标签页在前台时每 30 秒拉一次，
  // 从群页返回时因为 pathname 变了会马上再拉一次（页码里读群时后端已记成看过）。
  useWhileVisible(loadGroups, 30_000, { atOnceWhenShown: true });

  const startGroup = useCallback(() => {
    if (!groupName.trim() || chosen.length === 0 || starting) return;
    setStarting(true);
    createGroup(groupName.trim(), chosen).then(
      (group) => {
        setStarting(false);
        setMaking(false);
        setChosen([]);
        setGroupName("");
        loadGroups();
        router.push(`/conversation/group/${group.id}`);
      },
      () => setStarting(false),
    );
  }, [chosen, groupName, loadGroups, router, starting]);

  const keep = [selectedId, call?.characterId].filter((id): id is string => !!id);
  const shown = characters && arrange(characters, latest, { preferences, query, keep, onScreen });
  const hiddenCount = shown?.hiddenCount ?? 0;
  // 搜索时隐藏的人照样出现，「已隐藏 n 位」和全部隐藏的空状态只在没有搜索时出现。
  const showsHidden = query.trim() === "" && hiddenCount > 0;

  // 群聊和私聊排在一起：置顶的在最前，其余按最近一条消息的时间交叉排列。
  const ordered = useMemo(() => {
    if (!shown) return [];
    const pinned = shown.rows
      .filter((row) => row.isPinned)
      .map((row) => ({ kind: "character" as const, at: "", row }));
    const rest = [
      ...shown.rows
        .filter((row) => !row.isPinned)
        .map((row) => ({
          kind: "character" as const,
          at: previewOf(latest[row.character.id])?.at ?? "",
          row,
        })),
      ...groups.map((group) => ({
        kind: "group" as const,
        at: group.last_message_at ?? group.last_topic_at ?? group.created_at,
        group,
      })),
    ].sort((a, b) => (a.at === b.at ? 0 : b.at > a.at ? 1 : -1));
    return [...pinned, ...rest];
  }, [groups, latest, shown]);

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-2 pt-3 pr-2 pb-2 pl-4">
        <h1 className="flex-1 text-list-title">{t.title}</h1>
        <Button variant="outline" size="sm" onClick={() => setMaking(true)}>
          <GroupCardIcon aria-hidden />
          {copy.play.group.create}
        </Button>
        <ServiceStatusButton />
        <Announcements userId={account?.id ?? null} />
      </header>

      <div className="flex shrink-0 items-center gap-1 pr-2 pb-2 pl-4">
        <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-lg bg-muted px-3 text-muted-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/50">
          <SearchIcon aria-hidden className="size-4 shrink-0" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.search}
            aria-label={t.search}
            className="min-w-0 flex-1 bg-transparent text-body text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>
        <ListFilter isOpen={isFilterOpen} onOpenChange={setFilterOpen} hiddenCount={hiddenCount} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {failure ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>{t.loadFailed}</EmptyTitle>
              <EmptyDescription>{failure.message}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              {failure.signedOut ? (
                <SignInButton />
              ) : (
                <Button variant="outline" onClick={reload}>
                  {t.retry}
                </Button>
              )}
            </EmptyContent>
          </Empty>
        ) : !shown ? (
          <Loading />
        ) : shown.rows.length === 0 && showsHidden ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>{t.allHidden}</EmptyTitle>
            </EmptyHeader>
            <EmptyContent>
              <Button variant="outline" onClick={() => setFilterOpen(true)}>
                {t.chooseShown}
              </Button>
            </EmptyContent>
          </Empty>
        ) : shown.rows.length === 0 ? (
          <p className="px-4 py-6 text-center text-preview text-muted-foreground">{t.noMatch}</p>
        ) : (
          <>
            <ul aria-label={t.title}>
              {ordered.map((item) =>
                item.kind === "group" ? (
                  <li key={`group-${item.group.id}`}>
                    <GroupRow
                      group={item.group}
                      characters={characters}
                      isOpen={item.group.id === openGroupId}
                      go={go}
                    />
                  </li>
                ) : (
                  <li key={item.row.character.id}>
                    <Row
                      row={item.row}
                      preview={previewOf(latest[item.row.character.id])}
                      call={call?.characterId === item.row.character.id ? call : null}
                      isSelected={item.row.character.id === selectedId}
                      now={now}
                      onSelect={() => {
                        if (item.row.character.id === selectedId) return;
                        go(`/conversation/${item.row.character.id}`);
                      }}
                      onTogglePin={() =>
                        tidy((p) =>
                          item.row.isPinned
                            ? unpin(p, item.row.character.id)
                            : pin(p, item.row.character.id),
                        )
                      }
                      onToggleHidden={() =>
                        tidy((p) => setShown(p, [item.row.character.id], item.row.isHidden))
                      }
                    />
                  </li>
                ),
              )}
            </ul>
            {showsHidden && (
              <button
                type="button"
                onClick={() => setFilterOpen(true)}
                className="w-full px-4 py-3 text-left text-meta text-muted-foreground outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset"
              >
                {t.hiddenCount(String(hiddenCount))}
              </button>
            )}
          </>
        )}
      </div>

      <Dialog open={making} onOpenChange={setMaking}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy.play.group.createTitle}</DialogTitle>
            <DialogDescription>{copy.play.group.createHint}</DialogDescription>
          </DialogHeader>
          <Input
            value={groupName}
            onChange={(event) => setGroupName(event.target.value)}
            placeholder="群名"
          />
          <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto py-2">
            {(characters ?? []).map((character) => {
              const picked = chosen.includes(character.id);
              return (
                <button
                  key={character.id}
                  type="button"
                  aria-pressed={picked}
                  onClick={() =>
                    setChosen((current) =>
                      current.includes(character.id)
                        ? current.filter((id) => id !== character.id)
                        : [...current, character.id],
                    )
                  }
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-2 py-2 text-left text-body transition-colors",
                    picked ? "border-primary bg-muted" : "border-border",
                  )}
                >
                  <MarkedAvatar
                    name={character.name}
                    src={character.avatar_url}
                    size="sm"
                  />
                  <span className="truncate">{character.name}</span>
                </button>
              );
            })}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMaking(false)} disabled={starting}>
              取消
            </Button>
            <Button
              onClick={startGroup}
              disabled={starting || !groupName.trim() || chosen.length === 0}
            >
              {starting ? copy.play.group.creating : copy.play.group.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** 列表里的一行群聊：成员头像、群名、人数和最近一句。 */
function GroupRow({
  group,
  characters,
  isOpen,
  go,
}: {
  group: GroupSummary;
  characters: Character[] | null;
  /** 这一群正开着：红点当场就消（后端进群时也会把它记成看过）。 */
  isOpen: boolean;
  go: (href: string) => void;
}) {
  const preview = group.preview;
  return (
    <button
      type="button"
      onClick={() => go(`/conversation/group/${group.id}`)}
      className="flex w-full items-center gap-3 px-4 py-2 text-left outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset"
    >
      <span className="flex shrink-0 -space-x-2">
        {group.members.slice(0, 2).map((member) => (
          <MarkedAvatar
            key={member.id}
            name={member.name}
            src={characters?.find((c) => c.id === member.id)?.avatar_url ?? null}
            size="sm"
          />
        ))}
      </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex items-baseline justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-body">{group.name}</span>
              {group.unseen && !isOpen && (
                <span className="size-2 shrink-0 rounded-full bg-primary" aria-hidden />
              )}
            </span>
            <span className="shrink-0 text-meta text-muted-foreground">
              {group.members.length} 人
            </span>
          </span>
        <span className="truncate text-preview text-muted-foreground">
          {preview ? `${preview.name}：${preview.zh || preview.text}` : copy.play.group.noHistory}
        </span>
      </span>
    </button>
  );
}

/**
 * 列表里的一行：一整个按钮，选中时 `aria-current`，铺中性的 bg-muted（不用她的颜色）；置顶的时间旁边有个小图钉。
 * 有没看过的搭话时时间前面一个她颜色（`her-mark`）的小圆点：列表栏不在她的子树里，只在圆点上套她的颜色变量；
 * 名字和最后一句不加深。
 * 右键、触屏长按、菜单键或 Shift+F10 打开行菜单（中性色）：置顶或取消置顶，在列表中隐藏或显示。
 */
function Row({
  row: { character, isPinned, isHidden, isUnseen },
  preview,
  call,
  isSelected,
  now,
  onSelect,
  onTogglePin,
  onToggleHidden,
}: {
  row: ListRow<Character>;
  preview: Preview | null;
  call: CallInList;
  isSelected: boolean;
  now: Date;
  onSelect: () => void;
  onTogglePin: () => void;
  onToggleHidden: () => void;
}) {
  const time = useCallTime(call?.state);
  // 长按打开菜单后，松手时浏览器可能还会补发一次点击；菜单打开之后、下一次按下之前的点击不打开对话。
  const openedMenu = useRef(false);
  const description = call ? (
    time ? (
      copy.call.listConnected(showTime(time))
    ) : (
      copy.call.dialing
    )
  ) : !preview ? (
    t.neverTalked
  ) : (
    <PreviewText preview={preview} name={character.name} />
  );
  return (
    <ContextMenu
      onOpenChange={(open) => {
        if (open) openedMenu.current = true;
      }}
    >
      <ContextMenuTrigger
        render={<button type="button" />}
        onPointerDown={() => (openedMenu.current = false)}
        onKeyDown={() => (openedMenu.current = false)}
        onClick={() => {
          if (!openedMenu.current) onSelect();
        }}
        aria-current={isSelected ? "page" : undefined}
        className={cn(
          "flex w-full items-center gap-3 px-4 py-2.5 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
          isSelected ? "bg-muted" : "hover:bg-muted/60",
        )}
      >
        <MarkedAvatar name={character.name} src={character.avatar_url} size="list" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex items-baseline gap-2">
            <span className="min-w-0 flex-1 truncate text-row-name">{character.name}</span>
            {((preview && !call) || isPinned) && (
              <span className="flex shrink-0 items-center gap-1 text-meta text-muted-foreground tabular-nums">
                {isUnseen && preview && !call && (
                  <>
                    <span aria-hidden style={herVars(character.color)} className="size-2 shrink-0 rounded-full bg-her-mark" />
                    <span className="sr-only">{t.unseen}</span>
                  </>
                )}
                {preview && !call && listTime(new Date(preview.at), now)}
                {isPinned && (
                  <>
                    <PinIcon aria-hidden className="size-3" />
                    <span className="sr-only">{t.pinned}</span>
                  </>
                )}
              </span>
            )}
          </span>
          <span className="truncate text-preview text-muted-foreground tabular-nums">{description}</span>
        </span>
      </ContextMenuTrigger>
      <ContextMenuContent>
        {/* 菜单项里的图标默认 16px、跟着菜单文字的颜色（DESIGN.md「行菜单」） */}
        <ContextMenuItem onClick={onTogglePin}>
          {isPinned ? <UnpinIcon aria-hidden /> : <PinIcon aria-hidden />}
          {isPinned ? t.unpin : t.pin}
        </ContextMenuItem>
        <ContextMenuItem onClick={onToggleHidden}>
          {isHidden ? <ShowIcon aria-hidden /> : <HideIcon aria-hidden />}
          {isHidden ? t.show : t.hide}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** 列表里的时间：今天写时刻（和气泡旁的时间一样写成 8:49），昨天写「昨天」，今年写月日，更早写年月日。 */
function listTime(at: Date, now: Date): string {
  const two = (n: number) => String(n).padStart(2, "0");
  switch (dayOf(at, now)) {
    case "today":
      return `${at.getHours()}:${two(at.getMinutes())}`;
    case "yesterday":
      return t.yesterday;
    case "thisYear":
      return t.monthDay(String(at.getMonth() + 1), String(at.getDate()));
    case "earlier":
      return t.fullDate(String(at.getFullYear()), String(at.getMonth() + 1), String(at.getDate()));
  }
}

/** 现在的时间，每分钟更新一次，过了午夜「今天」「昨天」会跟着变。 */
function useMinute(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function Loading() {
  return (
    <div className="flex flex-col" aria-label={t.loading} aria-busy>
      {[0, 1].map((i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-2.5">
          <Skeleton className="size-list-avatar shrink-0 rounded-full" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        </div>
      ))}
    </div>
  );
}
