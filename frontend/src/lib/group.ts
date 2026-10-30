// The group chats over the API: the user's groups, one group with its whole history, starting
// one (拉群), renaming it, turning its scheduler on or off, dissolving it (解散), the user's own
// line, and raising a topic by hand (the scheduler raises them about every four hours on its own).

import { api, json } from "@/lib/api";

export type GroupMember = { id: string; name: string };

export type GroupLine = {
  speaker: string;
  name: string;
  /** Her image colour; null for the user's own lines. */
  color: string | null;
  /** Her Japanese, or the user's own words. */
  text: string;
  /** Her Chinese subtitle; empty for the user's lines. */
  zh: string;
  created_at: string;
};

export type GroupTopic = {
  id: string;
  raised_by: string;
  text: string;
  created_at: string;
  open: boolean;
};

/** One topic and its lines, as the history holds them. */
export type GroupTopicEntry = { topic: GroupTopic; lines: GroupLine[] };

/** A group as the list shows it: a preview of its latest line, not its whole history. */
export type GroupSummary = {
  id: string;
  name: string;
  on: boolean;
  created_at: string;
  last_topic_at: string | null;
  /** When anyone last said anything in it; the list orders by this. */
  last_message_at: string | null;
  members: GroupMember[];
  preview: GroupLine | null;
  /** Whether anyone has said anything since the page was last open. */
  unseen: boolean;
};

/** One group, with its whole readable history. */
export type GroupDetail = {
  id: string;
  name: string;
  on: boolean;
  created_at: string;
  last_topic_at: string | null;
  members: GroupMember[];
  /** The latest topic and its lines; null before the first one. */
  topic: GroupTopic | null;
  lines: GroupLine[];
  /** Every topic, oldest first. */
  history: GroupTopicEntry[];
};

export async function listGroups(): Promise<GroupSummary[]> {
  return json(await api("/api/groups"));
}

export async function getGroup(groupId: string): Promise<GroupDetail> {
  return json(await api(`/api/group/${encodeURIComponent(groupId)}`));
}

/** Start a group with these members (拉群), the first topic raised right away. */
export async function createGroup(name: string, characterIds: string[]): Promise<GroupDetail> {
  return json(
    await api("/api/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, character_ids: characterIds }),
    }),
  );
}

export async function renameGroup(groupId: string, name: string): Promise<GroupDetail> {
  return json(
    await api(`/api/group/${encodeURIComponent(groupId)}/name`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  );
}

export async function setGroupOn(groupId: string, on: boolean): Promise<GroupDetail> {
  return json(
    await api(`/api/group/${encodeURIComponent(groupId)}/on`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }),
    }),
  );
}

/** Set who is in the group (the people already in it, or others). */
export async function setGroupMembers(
  groupId: string,
  characterIds: string[],
): Promise<GroupDetail> {
  return json(
    await api(`/api/group/${encodeURIComponent(groupId)}/members`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ character_ids: characterIds }),
    }),
  );
}

/** The user says a line, an ordinary member's; answers once it is written down. */
export async function sayInGroup(groupId: string, text: string): Promise<GroupDetail> {
  return json(
    await api(`/api/group/${encodeURIComponent(groupId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  );
}

/** Raise a topic now, as the scheduler does. */
export async function raiseGroupTopic(groupId: string): Promise<GroupDetail> {
  return json(await api(`/api/group/${encodeURIComponent(groupId)}/topic`, { method: "POST" }));
}

/** Dissolve the group (解散); it leaves the list. */
export async function dissolveGroup(groupId: string): Promise<void> {
  await api(`/api/group/${encodeURIComponent(groupId)}`, { method: "DELETE" });
}
