"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { NumberInput } from "@/components/app/admin/NumberInput";
import { useSubmitCheck } from "@/components/admin/useSubmitCheck";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { copy } from "@/i18n";
import { exemptingKeysOf, getAdminConfig, isAvailable } from "@/lib/adminConfig";
import {
  limitDraft,
  limitsInput,
  setUserLimits,
  type AdminUserDetails,
  type LimitDraft,
  type LimitProblem,
} from "@/lib/adminUsers";
import { sayServices } from "@/lib/exemptingKeys";
import { toFailure, type Failure } from "@/lib/failure";
import type { OwnService } from "@/lib/localOwnKeys";

const t = copy.admin.users.limitsDialog;

const NOTE_MAX = 500;
const COUNT_MAX = 100_000;

/**
 * 设定或修改一位用户的单独限额：每小时的回合数、通话次数、照片数、光顾次数和朗读次数各自选「跟随全站 / 设定次数 / 不限 /
 * 只能用自带密钥」，次数从 1 起；附一句只有管理者看得到的备注。「只能用自带密钥」是单列的一项，
 * 不再让人填 0：全站限额里 0 是不限，同一个数字两处意思相反容易配错。`user` 为 null 时对话框关着；
 * 保存成功后把后端返回的这位用户交给 `onSaved`。保存是表单的提交，用 default（DESIGN.md「Buttons」）。
 */
export function UserLimitsDialog({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUserDetails | null;
  onClose: () => void;
  onSaved: (user: AdminUserDetails) => void;
}) {
  const [turns, setTurns] = useState<LimitDraft>(limitDraft(null));
  const [calls, setCalls] = useState<LimitDraft>(limitDraft(null));
  const [photos, setPhotos] = useState<LimitDraft>(limitDraft(null));
  const [visits, setVisits] = useState<LimitDraft>(limitDraft(null));
  const [readAlouds, setReadAlouds] = useState<LimitDraft>(limitDraft(null));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  /** 全站现在的每小时回合数、通话次数、照片数、光顾次数和朗读次数（配置页「限额」一项当前生效的值）；读不到时选项只写「跟随全站」。 */
  const [site, setSite] = useState<{
    turns: number;
    calls: number;
    photos: number | null;
    visits: number | null;
    readAlouds: number | null;
  } | null>(null);
  /** 全站现在的免限额密钥（同一项里的三个开关）；读不到时「只能用自带密钥」的说明不点名。 */
  const [exemptingKeys, setExemptingKeys] = useState<OwnService[] | null>(null);
  const check = useSubmitCheck<HTMLFormElement>();
  const noteId = useId();

  useEffect(() => {
    if (!user) return;
    let current = true;
    getAdminConfig().then(
      (config) => {
        const limits = config.limits;
        if (!current || !isAvailable(limits)) return;
        setExemptingKeys(exemptingKeysOf(limits.effective));
        const {
          turns_per_hour: turns,
          calls_per_hour: calls,
          photos_per_hour: photos,
          visits_per_hour: visits,
          read_alouds_per_hour: readAlouds,
        } = limits.effective;
        if (typeof turns === "number" && typeof calls === "number") {
          setSite({
            turns,
            calls,
            photos: typeof photos === "number" ? photos : null,
            visits: typeof visits === "number" ? visits : null,
            readAlouds: typeof readAlouds === "number" ? readAlouds : null,
          });
        }
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, [user]);

  // Opened afresh: start from what the user has now.
  useEffect(() => {
    if (!user) return;
    setTurns(limitDraft(user.limits?.turns_per_hour ?? null));
    setCalls(limitDraft(user.limits?.calls_per_hour ?? null));
    setPhotos(limitDraft(user.limits?.photos_per_hour ?? null));
    setVisits(limitDraft(user.limits?.visits_per_hour ?? null));
    setReadAlouds(limitDraft(user.limits?.read_alouds_per_hour ?? null));
    setNote(user.limits?.note ?? "");
    setFailure(null);
    check.reset();
  }, [user]);

  const result = limitsInput({ turns, calls, photos, visits, readAlouds });
  // 不先报错、保存键不变灰：点过一次保存才标出不对的项（见 useSubmitCheck）。
  const problemOf = (field: LimitProblem["field"]) =>
    check.shown && "problems" in result ? result.problems.filter((p) => p.field === field) : [];

  function close() {
    if (!busy) onClose();
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    if (!("input" in result)) {
      check.refuse();
      return;
    }
    const { input } = result;
    setBusy(true);
    setFailure(null);
    try {
      onSaved(await setUserLimits(user.id, input, note));
    } catch (e) {
      setFailure(toFailure(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={user !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent showCloseButton={false} className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <form ref={check.ref} onSubmit={save} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{t.title(user?.name ?? "")}</DialogTitle>
            <DialogDescription>{t.hint}</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <LimitField
              label={t.turns}
              draft={turns}
              onChange={setTurns}
              site={site?.turns ?? null}
              ownKeysHint={t.turnsOwnKeysHint}
              problems={problemOf("turns")}
            />
            <LimitField
              label={t.calls}
              draft={calls}
              onChange={setCalls}
              site={site?.calls ?? null}
              ownKeysHint={
                exemptingKeys?.length ? sayServices(t.callsOwnKeysHint, exemptingKeys) : t.callsOwnKeysHintUnknown
              }
              problems={problemOf("calls")}
            />
            <LimitField
              label={t.photos}
              draft={photos}
              onChange={setPhotos}
              site={site?.photos ?? null}
              siteCount={t.sitePhotos}
              units={t.photoUnits}
              ownKeysHint={t.photosOwnKeysHint}
              problems={problemOf("photos")}
            />
            <LimitField
              label={t.visits}
              draft={visits}
              onChange={setVisits}
              site={site?.visits ?? null}
              ownKeysHint={t.visitsOwnKeysHint}
              problems={problemOf("visits")}
            />
            <LimitField
              label={t.readAlouds}
              draft={readAlouds}
              onChange={setReadAlouds}
              site={site?.readAlouds ?? null}
              ownKeysHint={t.readAloudsOwnKeysHint}
              problems={problemOf("readAlouds")}
            />
            <Field>
              <FieldLabel htmlFor={noteId}>{t.note}</FieldLabel>
              <Textarea id={noteId} value={note} onChange={(e) => setNote(e.target.value)} maxLength={NOTE_MAX} />
              <FieldDescription>{t.noteHint}</FieldDescription>
            </Field>
          </FieldGroup>
          {failure && <FailureNotice failure={failure} />}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={close} disabled={busy}>
              {copy.common.cancel}
            </Button>
            <Button type="submit" disabled={busy}>
              {busy && <Spinner data-icon="inline-start" />}
              {t.confirm}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * 一项限额：先选种类，选了「设定次数」就在这一项底下填数字。四个选项竖排：手机宽度上横排放不下。
 * 照片按张数说（`siteCount`、`units`），回合和通话按次。
 */
function LimitField({
  label,
  draft,
  onChange,
  site,
  siteCount = t.siteCount,
  units = t.units,
  ownKeysHint,
  problems,
}: {
  label: string;
  draft: LimitDraft;
  onChange: (draft: LimitDraft) => void;
  /** 全站现在的数字，0 是不限；不知道时 null。 */
  site: number | null;
  siteCount?: (n: number) => string;
  units?: string;
  /** 「只能用自带密钥」放行的是哪些。 */
  ownKeysHint: string;
  /** 点过保存后这一项不对的地方。 */
  problems: LimitProblem[];
}) {
  const id = useId();
  const needsCount = problems.some((p) => p.reason === "count");
  const needsOne = problems.some((p) => p.reason === "needsOne");
  const choices: { value: LimitDraft["choice"]; label: string; description?: string }[] = [
    { value: "default", label: site === null ? t.choices.default : t.defaultIs(siteCount(site)) },
    { value: "number", label: t.choices.number },
    { value: "unlimited", label: t.choices.unlimited },
    { value: "own_keys", label: t.choices.ownKeys, description: ownKeysHint },
  ];
  return (
    <FieldSet>
      <FieldLegend variant="label">{label}</FieldLegend>
      <RadioGroup
        value={draft.choice}
        onValueChange={(choice) => onChange({ ...draft, choice: choice as LimitDraft["choice"] })}
        aria-invalid={needsOne || undefined}
      >
        {choices.map((choice) => (
          <Field key={choice.value} orientation="horizontal">
            <RadioGroupItem value={choice.value} id={`${id}-${choice.value}`} />
            <FieldContent>
              <FieldLabel htmlFor={`${id}-${choice.value}`}>{choice.label}</FieldLabel>
              {choice.description && <FieldDescription>{choice.description}</FieldDescription>}
              {choice.value === "number" && draft.choice === "number" && (
                <div className="mt-1 flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <NumberInput
                      label={t.count(label)}
                      value={draft.count}
                      onChange={(n) => onChange({ ...draft, count: n })}
                      min={1}
                      max={COUNT_MAX}
                      isIntegerOnly
                      isInvalid={needsCount}
                    />
                    <span className="text-sm text-muted-foreground">{units}</span>
                  </div>
                  {needsCount && <FieldError>{t.needsCount}</FieldError>}
                </div>
              )}
            </FieldContent>
          </Field>
        ))}
      </RadioGroup>
      {needsOne && <FieldError>{t.needsOne}</FieldError>}
    </FieldSet>
  );
}
