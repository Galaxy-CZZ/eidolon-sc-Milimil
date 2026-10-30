// The bar's text box (.scratch/bar-room spec「文本框和打字」): a line of a visit laid out in pages
// of at most four rows, and how much of a page is typed out by a moment.

/** One line of a visit as the text box shows it: hers in Japanese with its Chinese subtitle, or
 * the producer's in Chinese. */
export type TextLine = { speaker: "her"; ja: string; zh: string } | { speaker: "producer"; zh: string };

/** One row of a page: the speaker's name and colon before the line's first row, and whether it is
 * her Chinese subtitle under her Japanese. */
export type TextRow = { name: string | null; text: string; subtitle: boolean };

export type TextPage = { rows: TextRow[] };

/** The width the text runs to: the box's 412 less 6 on either side. */
export const TEXT_WIDTH = 400;
/** The box's 65 holds four rows of 16. */
export const ROWS_PER_PAGE = 4;

export function paginate(
  line: TextLine,
  { names, measure }: { names: { her: string; producer: string }; measure: (text: string) => number },
): TextPage[] {
  const name = `${line.speaker === "her" ? names.her : names.producer}：`;
  const first = line.speaker === "her" ? line.ja : line.zh;
  const rows = wrapText(first, TEXT_WIDTH, measure, measure(name)).map((text, i) => ({ name: i === 0 ? name : null, text, subtitle: false }));
  if (line.speaker === "her") rows.push(...wrapText(line.zh, TEXT_WIDTH, measure).map((text) => ({ name: null, text, subtitle: true })));
  const pages: TextPage[] = [];
  for (let i = 0; i < rows.length; i += ROWS_PER_PAGE) pages.push({ rows: rows.slice(i, i + ROWS_PER_PAGE) });
  return pages;
}

/** A Latin word (drink names in the subtitles), kept whole on a row where it fits; any other
 * character stands alone. */
const TOKEN = /[A-Za-z0-9'’.,!?%-]+|\s+|./gsu;
/** What may hang past the row's end rather than open the next row. */
const CLOSING = /^[、。，．,.！？!?」』）)】〉》…ー〜～：；:;]$/u;

/** `text` broken into rows `width` wide, the first `indent` in: Latin words kept whole where
 * they fit, closing punctuation hung past the end rather than opening a row. */
export function wrapText(text: string, width: number, measure: (text: string) => number, indent = 0): string[] {
  const rows: string[] = [];
  let row = "";
  let room = width - indent;
  const breakRow = () => {
    rows.push(row.trimEnd());
    row = "";
    room = width;
  };
  for (const token of text.match(TOKEN) ?? []) {
    if (/^\s+$/u.test(token)) {
      if (row) row += " ";
      continue;
    }
    if (measure(row + token) <= room || (row && CLOSING.test(token))) {
      row += token;
      continue;
    }
    if (row.trim()) breakRow();
    else row = "";
    // 一个词比一整行还长：一个字一个字地放。
    for (const ch of token) {
      if (row && measure(row + ch) > room) breakRow();
      row += ch;
    }
  }
  if (row.trim() || rows.length === 0) rows.push(row.trimEnd());
  return rows;
}

/** Characters typed a second (the original's one a frame at 30 frames a second; slowed to 18 so
 * her voiced lines are still typing out when the TTS arrives, which hides the synthesis latency). */
export const CHARS_PER_SECOND = 18;

/** When a page started typing out, and whether a tap finished it at once. */
export type Typing = { startedAt: number; finished: boolean };

/** What a page types out: her Japanese, which her subtitle keeps pace with; on a page of her
 * subtitle alone, or of the producer's line, the text there. */
function typedRows(page: TextPage): TextRow[] {
  const main = page.rows.filter((row) => !row.subtitle);
  return main.length ? main : page.rows;
}

function lengthOf(rows: TextRow[]): number {
  return rows.reduce((sum, row) => sum + [...row.text].length, 0);
}

/** How many characters of the page are typed out by `now` (all of them once tapped). */
export function typedChars(page: TextPage, typing: Typing, now: number): number {
  const length = lengthOf(typedRows(page));
  if (typing.finished) return length;
  return Math.min(length, Math.max(0, Math.floor(((now - typing.startedAt) * CHARS_PER_SECOND) / 1000)));
}

/** When the page is typed out, unless a tap finishes it first. */
export function typedOutAt(page: TextPage, typing: Typing): number {
  return typing.startedAt + Math.ceil((lengthOf(typedRows(page)) * 1000) / CHARS_PER_SECOND);
}

export function isTypedOut(page: TextPage, typing: Typing, now: number): boolean {
  return typedChars(page, typing, now) === lengthOf(typedRows(page));
}

/** The page's rows as far as `typed` characters: the names from the start; her subtitle shown in
 * step with her Japanese above it. */
export function shownRows(page: TextPage, typed: number): TextRow[] {
  const typedRowsOfPage = typedRows(page);
  const length = lengthOf(typedRowsOfPage);
  const pacedLength = lengthOf(page.rows.filter((row) => !typedRowsOfPage.includes(row)));
  const paced = length ? Math.round((Math.min(typed, length) / length) * pacedLength) : 0;
  let remaining = { typed, paced };
  return page.rows.map((row) => {
    const key = typedRowsOfPage.includes(row) ? "typed" : "paced";
    const chars = [...row.text];
    const shown = Math.min(chars.length, Math.max(0, remaining[key]));
    remaining = { ...remaining, [key]: remaining[key] - shown };
    return { ...row, text: chars.slice(0, shown).join("") };
  });
}
