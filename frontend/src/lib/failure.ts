import { ApiError } from "@/lib/api";

/** An error to show on a page; `signedOut` adds a link to the sign-in page, `toOwnKeys` a
 * button to the settings page's own keys, when filling them in there settles it.
 * `countsTowardLimit` is set when it is known whether what failed still counts towards the
 * hourly limit (GLOSSARY.md「限额」); left out when it is not known or does not apply. */
export type Failure = { message: string; signedOut: boolean; toOwnKeys?: boolean; countsTowardLimit?: boolean };

export function toFailure(e: unknown): Failure {
  const failure: Failure = { message: (e as Error).message, signedOut: e instanceof ApiError && e.unauthorized };
  // Refused for the limit: own keys get around it (GLOSSARY.md「免限额密钥」). Failed on the user's own
  // key: theirs to fix.
  if (e instanceof ApiError && (e.overLimit || e.code === "own_key")) failure.toOwnKeys = true;
  return failure;
}
