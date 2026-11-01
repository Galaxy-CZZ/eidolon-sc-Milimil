// 朋友圈页的时间线（GLOSSARY.md「朋友圈」「动态」，DESIGN.md「朋友圈页」）：一行底下 Meta 字号的那一行怎么写。
// 时间线只有 30 天内的动态，所以不写日期，只写离现在多久。

import {
  Cloud,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
  type LucideIcon,
  Sun,
} from "lucide-react";

import { copy } from "@/i18n";
import { COMMENT_LENGTH, type Moment, type MomentComment, type WeatherKind } from "@/lib/api";

const t = copy.moments;

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

/** 一条动态露出（`posted_at`）离 `now` 多久：不到 1 分钟「刚刚」（钟慢了、露出在将来的也是），不到 1 小时「N 分钟前」，
 * 不到 24 小时「N 小时前」；再早按本地日历算差几天，差 1 天「昨天」，其余「N 天前」。 */
export function postedText(postedAt: string, now: Date): string {
  const at = new Date(postedAt);
  const elapsed = now.getTime() - at.getTime();
  if (elapsed < MINUTE) return t.justNow;
  if (elapsed < HOUR) return t.minutesAgo(Math.floor(elapsed / MINUTE));
  if (elapsed < 24 * HOUR) return t.hoursAgo(Math.floor(elapsed / HOUR));
  const days = calendarDaysBetween(at, now);
  return days <= 1 ? t.yesterday : t.daysAgo(days);
}

/** `at` 那天到 `now` 那天隔了几天（本地日历，夏令时换算不影响）。 */
function calendarDaysBetween(at: Date, now: Date): number {
  const dayOf = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / (24 * HOUR);
  return dayOf(now) - dayOf(at);
}

/** 天气每一档的图标。 */
const WEATHER_ICONS: Record<WeatherKind, LucideIcon> = {
  clear: Sun,
  cloudy: CloudSun,
  overcast: Cloud,
  fog: CloudFog,
  rain: CloudRain,
  snow: CloudSnow,
  thunder: CloudLightning,
};

/** Meta 一行的一段：时间，带地图链接的地名，或天气（图标、读屏读的档位名和整数气温）。 */
export type MetaPart =
  | { kind: "time"; text: string }
  | { kind: "place"; text: string; href: string }
  | { kind: "weather"; text: string; icon: LucideIcon; label: string };

/** 评论区的一条：偶像的评论和她回制作人的，日语加字幕；制作人的，照他打的原样。都是「名字：」打头。 */
export type ReactionLine =
  | { kind: "idol"; by: string; ja: string; zh: string }
  | { kind: "producer"; by: string; text: string };

/** 一条动态下面那一块（`bg-muted` 圆角）：赞的人那一行（没人赞为 null）和评论区。 */
export type Reactions = {
  likers: string | null;
  comments: ReactionLine[];
};

/** 一条动态下面那一块写什么：赞的人按露出先后用「，」连成一行，他赞了排最前、写「制作人」；评论按先后，
 * 他的评论排在偶像的后面，她回他的（露出了才有）再跟在后面，写「<她的名字> 回复 制作人：」。都没有时为 null，
 * 这一块不出现。别的偶像的名字从 `nameOf` 取，她的名字是 `herName`。 */
export function reactions(
  moment: Moment,
  nameOf: (characterId: string) => string,
  herName: string,
): Reactions | null {
  const likers = [...(moment.producer_liked ? [t.producer] : []), ...moment.likes.map(nameOf)];
  const comments: ReactionLine[] = moment.comments.map(({ character_id, ja, zh }: MomentComment) => ({
    kind: "idol",
    by: t.commentedBy(nameOf(character_id)),
    ja,
    zh,
  }));
  if (moment.producer_comment) {
    comments.push({ kind: "producer", by: t.commentedBy(t.producer), text: moment.producer_comment.text });
    if (moment.reply) comments.push({ kind: "idol", by: t.repliedBy(herName), ...moment.reply });
  }
  if (likers.length === 0 && comments.length === 0) return null;
  return { likers: likers.length > 0 ? likers.join(t.likersSeparator) : null, comments };
}

/** 行尾「⋯」里的一项。 */
export type MomentAction = { action: "like" | "unlike" | "comment" | "uncomment"; label: string; disabled: boolean };

/** 行尾「⋯」里依次有哪几项：「赞」（赞过了是「取消赞」）、「评论」（他评论过以后不能点），评论过时再加「删除评论」。 */
export function momentActions(moment: Moment): MomentAction[] {
  const commented = moment.producer_comment !== null;
  return [
    moment.producer_liked
      ? { action: "unlike", label: t.actions.unlike, disabled: false }
      : { action: "like", label: t.actions.like, disabled: false },
    { action: "comment", label: t.actions.comment, disabled: commented },
    ...(commented ? [{ action: "uncomment" as const, label: t.actions.uncomment, disabled: false }] : []),
  ];
}

/** 评论有几个字：去掉首尾空白，按字（码点）数，emoji 一个算一个，同后端。 */
export function commentLength(text: string): number {
  return Array.from(text.trim()).length;
}

/** 评论能不能发：去掉首尾空白后 1 到 `COMMENT_LENGTH` 个字。 */
export function canSendComment(text: string): boolean {
  const length = commentLength(text);
  return length >= 1 && length <= COMMENT_LENGTH;
}

/** Meta 一行从左到右的几段，中间用分隔点连：时间、地名（点开看地图）、天气。没有的部分不出现，分隔点跟着省掉。 */
export function metaParts(moment: Moment, now: Date): MetaPart[] {
  const parts: MetaPart[] = [{ kind: "time", text: postedText(moment.posted_at, now) }];
  if (moment.place) parts.push({ kind: "place", text: moment.place.name, href: moment.place.map });
  if (moment.weather) {
    const { kind, temperature } = moment.weather;
    parts.push({ kind: "weather", text: `${temperature}°`, icon: WEATHER_ICONS[kind], label: t.weather[kind] });
  }
  return parts;
}
