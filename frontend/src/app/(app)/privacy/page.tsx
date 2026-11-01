import { AppLink } from "@/components/app/AppLink";
import { PageShell } from "@/components/app/PageShell";
import { SectionHeading, SubpageHeader } from "@/components/app/SubpageHeader";
import { LegalFooter } from "@/components/LegalFooter";
import { PrivacyContact } from "@/components/PrivacyContact";
import { copy } from "@/i18n";
import { interpolate } from "@/i18n/interpolate";

const t = copy.privacy;

export const metadata = { title: copy.legal.pageTitle(t.title) };

export default function PrivacyPage() {
  return (
    <PageShell header={<SubpageHeader title={t.title} backHref="/" />} footer={<LegalFooter />}>
      <div className="flex flex-col gap-8">
        {t.sections.map((section) => (
          <section key={section.title} className="flex flex-col gap-3">
            <SectionHeading>{section.title}</SectionHeading>
            {section.items.length > 0 && (
              // 和使用条款同样的条目：名字加粗在上，正文在下，行间细分隔线。
              <dl className="flex flex-col divide-y">
                {section.items.map((item) => (
                  <div key={item.term} className="flex flex-col gap-1 py-3">
                    <dt className="text-body font-semibold">{item.term}</dt>
                    <dd className="text-body">
                      {"links" in item && item.links ? interpolate(item.text, linked(item.links)) : item.text}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            {section.notes.map((note) => (
              <p key={note} className="text-body">
                {note}
              </p>
            ))}
          </section>
        ))}
        <PrivacyContact />
        <p className="text-meta text-muted-foreground">{t.lastUpdated}</p>
      </div>
    </PageShell>
  );
}

/** 条目正文里 `{名字}` 处的外部链接，新标签页打开，不带本站地址过去。 */
function linked(links: Record<string, { label: string; href: string }>) {
  return Object.fromEntries(
    Object.entries(links).map(([name, link]) => [
      name,
      <AppLink key={name} href={link.href} target="_blank" rel="noopener noreferrer">
        {link.label}
      </AppLink>,
    ]),
  );
}
