"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Message, MessageAvatar, MessageContent, MessageHeader } from "@/components/ui/message";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { copy } from "@/i18n";
import type { Character } from "@/lib/api";
import {
  dissolveGroup,
  getGroup,
  renameGroup,
  sayInGroup,
  setGroupMembers,
  type GroupDetail,
  type GroupLine,
  type GroupTopic,
} from "@/lib/group";
import { formatTimestamp } from "@/lib/timestamp";
import { cn } from "@/lib/utils";
import { BackIcon, SendIcon } from "@/theme/icons";

import { useDirectory } from "./ConversationDirectory";

const t = copy.play.group;

/** 有对话在聊时多久重新读一次；没在聊时慢一些。台词是后台一句一句写的。 */
const POLL_UNDER_WAY_MS = 3_000;
const POLL_IDLE_MS = 15_000;

/**
 * 一个群的页面（`/conversation/group/<id>`），和私聊同一套界面：页首是群名、成员头像和人数，
 * 下面是全部历史（每个话题一条分隔，台词按时间排），底部是输入栏。页首可以改群名（铅笔）、
 * 拉人（「成员」）和解散（确认后回到对话列表）。台词在后台一句一句生成，所以这里隔几秒重读一次，
 * 用户随时能在中间插话。
 */
export function GroupConversation({
  groupId,
  onBack,
}: {
  groupId: string;
  onBack?: () => void;
}) {
  const router = useRouter();
  const { characters } = useDirectory();
  const isFullScreen = !useMediaQuery("(min-width: 768px)", true);
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<null | "sending" | "renaming" | "picking" | "dissolving">(
    null,
  );
  const [draft, setDraft] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState("");
  const [picking, setPicking] = useState(false);
  const [rosterOpen, setRosterOpen] = useState(false);
  const [chosen, setChosen] = useState<string[]>([]);
  const [askingDissolve, setAskingDissolve] = useState(false);
  const bottom = useRef<HTMLDivElement | null>(null);
  const byId = useMemo(
    () => new Map((characters ?? []).map((c) => [c.id, c])),
    [characters],
  );
  const open = group?.topic?.open ?? false;

  const load = useCallback(() => {
    getGroup(groupId).then(
      (state) => {
        setGroup(state);
        setFailed(false);
      },
      () => setFailed(true),
    );
  }, [groupId]);

  useEffect(() => {
    load();
  }, [load]);

  const count = group ? group.history.reduce((n, entry) => n + entry.lines.length, 0) : 0;
  // 第一次进来直接落到底，别从上头一路滑下去（那一段看着像在加载）；此后再有新消息，
  // 才顺着滑过去。换了一个群聊，就当又是一次第一次。
  const beenThere = useRef(false);
  useEffect(() => {
    beenThere.current = false;
  }, [groupId]);
  useEffect(() => {
    if (count === 0) return;
    bottom.current?.scrollIntoView({
      behavior: beenThere.current ? "smooth" : "auto",
      block: "end",
    });
    beenThere.current = true;
  }, [count]);

  useEffect(() => {
    const id = window.setInterval(load, open ? POLL_UNDER_WAY_MS : POLL_IDLE_MS);
    return () => window.clearInterval(id);
  }, [load, open]);

  const run = useCallback(
    async (
      what: "sending" | "renaming" | "picking" | "dissolving",
      work: () => Promise<GroupDetail>,
    ) => {
      setBusy(what);
      try {
        setGroup(await work());
        setFailed(false);
      } catch {
        setFailed(true);
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const send = useCallback(() => {
    const value = draft.trim();
    if (!value || !group?.on || busy) return;
    setDraft("");
    void run("sending", () => sayInGroup(groupId, value));
  }, [busy, draft, group?.on, groupId, run]);

  const openRename = useCallback(() => {
    setNewName(group?.name ?? "");
    setRenaming(true);
  }, [group?.name]);

  const confirmRename = useCallback(() => {
    const value = newName.trim();
    if (!value || busy) return;
    setRenaming(false);
    void run("renaming", () => renameGroup(groupId, value));
  }, [busy, groupId, newName, run]);

  const openPicker = useCallback(() => {
    setChosen(group?.members.map((m) => m.id) ?? []);
    setPicking(true);
  }, [group?.members]);

  const confirmMembers = useCallback(() => {
    if (chosen.length === 0 || busy) return;
    setPicking(false);
    void run("picking", () => setGroupMembers(groupId, chosen));
  }, [busy, chosen, groupId, run]);

  const confirmDissolve = useCallback(() => {
    if (busy) return;
    setAskingDissolve(false);
    setBusy("dissolving");
    void dissolveGroup(groupId).then(
      () => {
        router.replace("/conversations");
      },
      () => {
        setBusy(null);
        setFailed(true);
      },
    );
  }, [busy, groupId, router]);

  const back = () => (onBack ? onBack() : router.push("/conversations"));

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        {isFullScreen && (
          <Button variant="ghost" size="icon" onClick={back} aria-label="返回">
            <BackIcon aria-hidden />
          </Button>
        )}
        <button
          type="button"
          onClick={() => setRosterOpen(true)}
          className="flex shrink-0 -space-x-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          title={t.roster}
        >
          {(group?.members ?? []).slice(0, 4).map((member) => (
            <MarkedAvatar
              key={member.id}
              name={member.name}
              src={byId.get(member.id)?.avatar_url ?? null}
              size="sm"
            />
          ))}
        </button>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={openRename}
            className="flex max-w-full items-center gap-1 truncate text-left text-body font-medium outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
            title={t.rename}
          >
            <span className="truncate">{group?.name ?? t.title}</span>
            <span className="text-meta text-muted-foreground">✎</span>
          </button>
          <p className="truncate text-meta text-muted-foreground">
            {group ? t.status(group.members.length) : ""}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={openPicker} disabled={busy !== null}>
          {t.members}
        </Button>
        {group?.on && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAskingDissolve(true)}
            disabled={busy !== null}
          >
            {t.dissolve}
          </Button>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto bg-muted/40 px-3 py-4">
        {failed && <FailureNotice failure={{ message: t.failed, signedOut: false }} />}
        {!group ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : group.history.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>{group.name}</EmptyTitle>
              <EmptyDescription>{t.noHistory}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
            {group.history.map((entry) => (
              <TopicBlock key={entry.topic.id} entry={entry} byId={byId} />
            ))}
            <div ref={bottom} />
          </div>
        )}
      </div>

      {group && !group.on && (
        <p className="px-4 py-2 text-center text-meta text-muted-foreground">{t.dissolved}</p>
      )}

      <div className="shrink-0 border-t border-border px-3 py-2">
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            placeholder={group?.on ? t.placeholder : t.dissolved}
            disabled={!group?.on || busy !== null}
            rows={1}
            className="min-h-9 flex-1 resize-none"
          />
          <Button
            onClick={send}
            disabled={!group?.on || busy !== null || !draft.trim()}
            aria-label={t.send}
          >
            <SendIcon aria-hidden />
          </Button>
        </div>
        {(busy === "sending" || open) && (
          <p className="mx-auto mt-1 w-full max-w-3xl text-meta text-muted-foreground">
            {busy === "sending" ? t.sending : t.raising}
          </p>
        )}
      </div>

      <Dialog open={rosterOpen} onOpenChange={setRosterOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.roster}</DialogTitle>
            <DialogDescription>
              {group?.name ?? t.title} · {group ? t.status(group.members.length) : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-80 flex-col gap-1 overflow-y-auto py-2">
            {(group?.members ?? []).map((member) => (
              <div key={member.id} className="flex items-center gap-2 px-2 py-1">
                <MarkedAvatar
                  name={member.name}
                  src={byId.get(member.id)?.avatar_url ?? null}
                  size="sm"
                />
                <span className="truncate text-body">{member.name}</span>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRosterOpen(false);
                openPicker();
              }}
              disabled={busy !== null}
            >
              {t.members}
            </Button>
            <Button onClick={() => setRosterOpen(false)}>关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={renaming} onOpenChange={setRenaming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.rename}</DialogTitle>
          </DialogHeader>
          <Input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                confirmRename();
              }
            }}
            autoFocus
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenaming(false)} disabled={busy !== null}>
              取消
            </Button>
            <Button onClick={confirmRename} disabled={busy !== null || !newName.trim()}>
              改名
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={picking} onOpenChange={setPicking}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.createTitle}</DialogTitle>
            <DialogDescription>{t.createHint}</DialogDescription>
          </DialogHeader>
          <div className="grid max-h-80 grid-cols-2 gap-2 overflow-y-auto py-2">
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
            <Button variant="outline" onClick={() => setPicking(false)} disabled={busy !== null}>
              取消
            </Button>
            <Button onClick={confirmMembers} disabled={busy !== null || chosen.length === 0}>
              {busy === "picking" ? t.creating : t.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={askingDissolve} onOpenChange={setAskingDissolve}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.dissolveTitle}</AlertDialogTitle>
            <AlertDialogDescription>{t.dissolveDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy !== null}>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={confirmDissolve}
              disabled={busy !== null}
            >
              {busy === "dissolving" ? t.dissolving : t.dissolveConfirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

/** 一个话题：一条「新话题」分隔，然后是它的台词。 */
function TopicBlock({
  entry,
  byId,
}: {
  entry: { topic: GroupTopic; lines: GroupLine[] };
  byId: Map<string, Character>;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-meta text-muted-foreground">
        <span className="h-px flex-1 bg-border" />
        <span>{t.newTopic}</span>
        <span>{formatTimestamp(entry.topic.created_at, { format: "auto", now: new Date() })}</span>
        <span className="h-px flex-1 bg-border" />
      </div>
      {entry.lines.map((line, index) => {
        const mine = line.color === null;
        return (
          <Message key={`${entry.topic.id}-${index}`} align={mine ? "end" : "start"}>
            {!mine && (
              <MessageAvatar>
                <MarkedAvatar
                  name={line.name}
                  src={byId.get(line.speaker)?.avatar_url ?? null}
                  size="bubble"
                />
              </MessageAvatar>
            )}
            <MessageContent>
              {!mine && <MessageHeader>{line.name}</MessageHeader>}
              <Bubble variant={mine ? "producer" : "her"} align={mine ? "end" : "start"}>
                <BubbleContent>
                  <p className="text-body whitespace-pre-wrap">{line.text}</p>
                  {line.zh && (
                    <p
                      className={cn(
                        "whitespace-pre-wrap text-meta",
                        mine ? "text-on-producer-ink/80" : "text-muted-foreground",
                      )}
                    >
                      {line.zh}
                    </p>
                  )}
                </BubbleContent>
              </Bubble>
            </MessageContent>
          </Message>
        );
      })}
    </section>
  );
}
