import { GroupConversation } from "@/components/conversations/GroupConversation";

export default async function Page({ params }: { params: Promise<{ groupId: string }> }) {
  const { groupId } = await params;
  return <GroupConversation groupId={groupId} />;
}
