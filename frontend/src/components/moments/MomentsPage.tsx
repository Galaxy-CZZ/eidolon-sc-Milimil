"use client";

import { useRouter } from "next/navigation";
import { Fragment, useEffect, useRef, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { ImageViewer } from "@/components/app/ImageViewer";
import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { PageShell } from "@/components/app/PageShell";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { copy } from "@/i18n";
import {
  ApiError,
  COMMENT_LENGTH,
  commentOnMoment,
  deleteMomentComment,
  getMoments,
  likeMoment,
  type Character,
  type Moment,
  type ProducerComment,
} from "@/lib/api";
import { toFailure, type Failure } from "@/lib/failure";
import {
  canSendComment,
  commentLength,
  metaParts,
  momentActions,
  reactions,
  type MomentAction,
  type Reactions,
} from "@/lib/moments";
import { CommentIcon, LikesIcon, MoreIcon, TrashIcon } from "@/theme/icons";
import { Ja } from "@/theme/Ja";

const t = copy.moments;

const CONFLICT = 409;

/**
 * 朋友圈页（`/moments`，DESIGN.md「朋友圈页」）：页首「朋友圈」大标题，下面一栏时间线（最宽 `max-w-3xl`、居中，同玩法页），
 * 最新的在上面，一条一行，行与行之间一条细线。打开时读一次；开着时外壳每分钟的那次轮询改成重读（`rereadOnPoll`），陆续露出的动态、赞和评论
 * 不用刷新就出现。每读到一次（服务器记成打开过）导航「朋友圈」上的点就清掉；打开时先在本地清掉。重读失败时留着上一次的，不提示。
 * 时间线和对话目录的角色都读到之前空着（免得名字先显示成 id，目录读不到时照样显示）；没有动态时一行 muted 的「还没有动态」。朋友圈关着（409）时换成对话列表，不留这一页在历史里。
 * 她的名字和头像从对话目录的角色里按 id 取，取不到（角色已经下架）时名字写 id、头像是名字的头一个字。
 * 赞、取消赞、评论、删评论成功后只改这一条，不重读时间线；在这之前发出去的重读回来了不用，下一次再读。
 */
export function MomentsPage() {
  const router = useRouter();
  const { characters, failure: directoryFailure, momentsRead, rereadOnPoll } = useDirectory();
  const [timeline, setTimeline] = useState<{ moments: Moment[]; readAt: Date } | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  // 在本地改过几次：读出去之后又改过的，读回来的已经落后了。
  const changes = useRef(0);

  useEffect(() => {
    let live = true;
    const read = (isFirst: boolean) => {
      const since = changes.current;
      getMoments().then(
        (moments) => {
          if (!live) return;
          momentsRead();
          if (changes.current !== since) return;
          setFailure(null);
          setTimeline({ moments, readAt: new Date() });
        },
        (e) => {
          if (!live) return;
          if (e instanceof ApiError && e.status === CONFLICT) router.replace("/conversations");
          else if (isFirst) setFailure(toFailure(e));
        },
      );
    };
    momentsRead();
    read(true);
    const stop = rereadOnPoll(() => read(false));
    return () => {
      live = false;
      stop();
    };
  }, [router, momentsRead, rereadOnPoll]);

  const byId = new Map((characters ?? []).map((character) => [character.id, character]));
  const change = (id: number, patch: Partial<Moment>) => {
    changes.current += 1;
    setTimeline((now) => now && { ...now, moments: now.moments.map((m) => (m.id === id ? { ...m, ...patch } : m)) });
  };
  return (
    <PageShell width="full" isInShell header={<h1 className="text-list-title">{t.title}</h1>}>
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-2">
        {failure && (
          <div className="py-4">
            <FailureNotice failure={failure} />
          </div>
        )}
        {timeline && (characters || directoryFailure) &&
          (timeline.moments.length === 0 ? (
            <p className="py-4 text-body text-muted-foreground">{t.empty}</p>
          ) : (
            <div className="flex flex-col divide-y">
              {timeline.moments.map((moment) => (
                <MomentRow
                  key={moment.id}
                  moment={moment}
                  character={byId.get(moment.character_id)}
                  nameOf={(id) => byId.get(id)?.name ?? id}
                  now={timeline.readAt}
                  onChange={(patch) => change(moment.id, patch)}
                />
              ))}
            </div>
          ))}
      </div>
    </PageShell>
  );
}

/** 行尾「⋯」弹出的每一项前面的图标。 */
const ACTION_ICONS: Record<MomentAction["action"], typeof LikesIcon> = {
  like: LikesIcon,
  unlike: LikesIcon,
  comment: CommentIcon,
  uncomment: TrashIcon,
};

/** 时间线的一行：左边她的头像；右边名字、日语正文、一行字幕（同对话气泡）、配图的缩略图（有的话）、
 * Meta 字号的「时间 · 地名 · 天气」（行尾「⋯」），有赞或评论时再下面一块，正在评论时最下面是评论输入。地名点开在新标签页打开地图，
 * 不把本站地址带过去。别的偶像的名字从 `nameOf` 取。赞、评论、删评论成功后用 `onChange` 改这一条；
 * 赞、取消赞、删评论失败时这一行最下面一条提示。 */
function MomentRow({
  moment,
  character,
  nameOf,
  now,
  onChange,
}: {
  moment: Moment;
  character: Character | undefined;
  nameOf: (characterId: string) => string;
  now: Date;
  onChange: (patch: Partial<Moment>) => void;
}) {
  const name = character?.name ?? moment.character_id;
  const block = reactions(moment, nameOf, name);
  const [acting, setActing] = useState(false);
  const [commenting, setCommenting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

  const act = async (action: MomentAction["action"]) => {
    setFailure(null);
    if (action === "comment") setCommenting(true);
    else if (action === "uncomment") setConfirming(true);
    else {
      const liked = action === "like";
      try {
        await likeMoment(moment.id, liked);
        onChange({ producer_liked: liked });
      } catch (e) {
        setFailure(toFailure(e));
      }
    }
  };
  const uncomment = async () => {
    setConfirming(false);
    setFailure(null);
    try {
      await deleteMomentComment(moment.id);
      onChange({ producer_comment: null, reply: null });
    } catch (e) {
      setFailure(toFailure(e));
    }
  };

  return (
    <article className="flex gap-3 py-4">
      <MarkedAvatar name={name} src={character?.avatar_url} size="lg" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-row-name">{name}</span>
        <div className="flex flex-col gap-0.5">
          <p className="text-body whitespace-pre-wrap">
            <Ja>{moment.ja}</Ja>
          </p>
          {moment.zh && <p className="text-subtitle text-muted-foreground">{moment.zh}</p>}
        </div>
        {moment.image && <Picture src={moment.image} />}
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 text-meta text-muted-foreground">
            {metaParts(moment, now).map((part, i) => (
              <Fragment key={i}>
                {i > 0 && " · "}
                {part.kind === "weather" ? (
                  <span className="whitespace-nowrap">
                    <part.icon role="img" aria-label={part.label} className="mr-1 inline size-3.5 align-middle" />
                    {part.text}
                  </span>
                ) : part.kind === "place" ? (
                  <a
                    href={part.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-sm underline-offset-2 outline-none hover:text-foreground hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {part.text}
                  </a>
                ) : (
                  <time dateTime={moment.posted_at}>{part.text}</time>
                )}
              </Fragment>
            ))}
          </p>
          <Popover open={acting} onOpenChange={setActing}>
            <PopoverTrigger render={<Button variant="secondary" size="icon-sm" aria-label={t.actions.open} />}>
              <MoreIcon aria-hidden />
            </PopoverTrigger>
            <PopoverContent side="left" className="flex w-auto flex-row gap-1 p-1">
              {momentActions(moment).map(({ action, label, disabled }) => {
                const Icon = ACTION_ICONS[action];
                return (
                  <Button
                    key={action}
                    variant="ghost"
                    size="sm"
                    disabled={disabled}
                    onClick={() => {
                      setActing(false);
                      void act(action);
                    }}
                  >
                    <Icon aria-hidden />
                    {label}
                  </Button>
                );
              })}
            </PopoverContent>
          </Popover>
        </div>
        {block && <ReactionsBlock reactions={block} />}
        {commenting && moment.producer_comment === null && (
          <CommentBox
            momentId={moment.id}
            herName={name}
            onSent={(kept) => {
              setCommenting(false);
              onChange({ producer_comment: kept, reply: null });
            }}
            onClose={() => setCommenting(false)}
          />
        )}
        {failure && (
          <div className="mt-1">
            <FailureNotice failure={failure} />
          </div>
        )}
      </div>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.uncomment.title}</AlertDialogTitle>
            <AlertDialogDescription>{t.uncomment.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{copy.common.cancel}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void uncomment()}>
              {t.uncomment.confirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </article>
  );
}

/** 一条动态下面的评论输入（同原型 A）：单行输入框（占位「评论<她的名字>的动态」）加「发送」，打开时就聚焦。
 * 回车发送，Esc 收起。去掉首尾空白后 1 到 140 个字才能发，超了在下面一行 destructive 的「141/140」。
 * 发不出去时保留打的字，上面一条提示原因。 */
function CommentBox({
  momentId,
  herName,
  onSent,
  onClose,
}: {
  momentId: number;
  herName: string;
  onSent: (kept: ProducerComment) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const length = commentLength(draft);
  const canSend = canSendComment(draft) && !sending;

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    setFailure(null);
    try {
      onSent(await commentOnMoment(momentId, draft));
    } catch (e) {
      setFailure(toFailure(e));
      setSending(false);
    }
  };

  return (
    <form
      className="mt-1 flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      {failure && <FailureNotice failure={failure} />}
      <div className="flex items-center gap-2">
        <Input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // 回车由表单发送；Esc 收起，输入法选字时的不算。
            if (e.key === "Escape" && !e.nativeEvent.isComposing) onClose();
          }}
          placeholder={t.commentBox.placeholder(herName)}
          aria-label={t.commentBox.label}
          className="h-9 flex-1"
        />
        <Button type="submit" size="lg" disabled={!canSend}>
          {t.commentBox.send}
        </Button>
      </div>
      {length > COMMENT_LENGTH && (
        <p className="text-meta text-destructive">{t.commentBox.count(length, COMMENT_LENGTH)}</p>
      )}
    </form>
  );
}

/** 配图的缩略图（GLOSSARY.md「配图」）：按原比例缩进 160px 见方，横图竖图都不变形，`rounded-lg`；本身是按钮，
 * 点了用 `ImageViewer` 整屏放大。 */
function Picture({ src }: { src: string }) {
  const [viewing, setViewing] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-label={t.picture.open}
        onClick={() => setViewing(true)}
        className="mt-1 w-fit overflow-hidden rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <img src={src} alt={t.picture.alt} className="block max-h-40 max-w-40" />
      </button>
      <ImageViewer src={src} title={t.picture.viewer} alt={t.picture.alt} open={viewing} onOpenChange={setViewing} />
    </>
  );
}

/** 一条动态下面 `bg-muted` 圆角的一块：心形加赞的人；细线下面是评论，「名字：日语」下面一行字幕；
 * 制作人的评论「制作人：内容」照他打的原样（保留换行），不当日语、没有字幕。 */
function ReactionsBlock({ reactions: { likers, comments } }: { reactions: Reactions }) {
  return (
    <div className="mt-1 flex flex-col gap-1 rounded-lg bg-muted px-3 py-2 text-sm">
      {likers && (
        <p className="flex gap-1.5">
          <LikesIcon role="img" aria-label={t.likedBy} className="mt-1 size-3.5 shrink-0" />
          <span className="font-medium">{likers}</span>
        </p>
      )}
      {likers && comments.length > 0 && <div className="h-px bg-foreground/10" />}
      {comments.map((comment, i) =>
        comment.kind === "producer" ? (
          <p key={i} className="whitespace-pre-wrap">
            <span className="font-medium">{comment.by}</span>
            {comment.text}
          </p>
        ) : (
          <div key={i} className="flex flex-col gap-0.5">
            <p>
              <span className="font-medium">{comment.by}</span>
              <Ja>{comment.ja}</Ja>
            </p>
            <p className="text-subtitle text-muted-foreground">{comment.zh}</p>
          </div>
        ),
      )}
    </div>
  );
}
