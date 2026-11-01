"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { SettingsSection } from "@/components/app/SettingsSection";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { Field, FieldContent, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/i18n";
import { switchMoments } from "@/lib/api";
import { toFailure, type Failure } from "@/lib/failure";

const t = copy.settings.moments;

/**
 * 设置「朋友圈」（GLOSSARY.md「朋友圈」）：一个开关，关了所有角色都不再给他发动态、不回他的评论，导航里也没有「朋友圈」；
 * 已有的动态留着、照常过期。存在服务器上，一拨马上存，别的设备上也生效；存不上就拨回去，照原话说明。
 * 值在导航外壳持有的账号里，一级「朋友圈」的摘要和导航跟着变。
 * 部署者没开朋友圈时账号里这一项为空，没有这一类：直接打开这个网址时回到设置页。
 */
export function MomentsSettings() {
  const { account, accountChanged } = useDirectory();
  const router = useRouter();
  const id = useId();
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const on = account?.moments ?? null;

  useEffect(() => {
    if (account && on === null) router.replace("/settings");
  }, [account, on, router]);

  if (!account || on === null) return null;

  const change = (next: boolean) => {
    setFailure(null);
    setSaving(true);
    accountChanged((current) => ({ ...current, moments: next }));
    switchMoments(next).then(
      () => setSaving(false),
      (e) => {
        accountChanged((current) => ({ ...current, moments: on }));
        setFailure(toFailure(e));
        setSaving(false);
      },
    );
  };

  return (
    <SettingsSection>
      <FieldGroup>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor={`${id}-on`}>{t.on}</FieldLabel>
          </FieldContent>
          <Switch id={`${id}-on`} checked={on} disabled={saving} onCheckedChange={change} />
        </Field>
        {failure && <FailureNotice failure={failure} />}
      </FieldGroup>
    </SettingsSection>
  );
}
