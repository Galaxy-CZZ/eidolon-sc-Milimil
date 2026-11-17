"use client";

import { useEffect, useId, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { SettingsSection } from "@/components/app/SettingsSection";
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/i18n";
import { getGroupsOn, setGroupsOn } from "@/lib/group";
import { toFailure, type Failure } from "@/lib/failure";

const t = copy.settings.groups;

/**
 * 设置「群聊」：一个总开关，关掉后所有群都不再开新话题——群聊的 token 花在这里。
 *
 * 关掉不删任何东西：群、话题、每句话都留着，群聊页照旧能进、能翻。想恢复再打开，
 * 下次调度就接上。
 */
export function GroupsSettings() {
  const id = useId();
  const [on, setOn] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    getGroupsOn().then(setOn, () => {});
  }, []);

  const change = (next: boolean) => {
    setFailure(null);
    setSaving(true);
    setOn(next);
    setGroupsOn(next).then(
      (now) => {
        setOn(now);
        setSaving(false);
      },
      (e) => {
        setOn(!next);
        setFailure(toFailure(e));
        setSaving(false);
      },
    );
  };

  if (on === null) return null;

  return (
    <SettingsSection>
      <FieldGroup>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor={`${id}-on`}>{t.on}</FieldLabel>
            <FieldDescription>{on ? t.onHint : t.offHint}</FieldDescription>
          </FieldContent>
          <Switch id={`${id}-on`} checked={on} disabled={saving} onCheckedChange={change} />
        </Field>
        {failure && <FailureNotice failure={failure} />}
      </FieldGroup>
    </SettingsSection>
  );
}
