"use client";

import { Mail } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

/** Konten Bantuan (tanpa hook auth — aman dipakai di dalam SimplePage). */
function HelpContent() {
  const { t } = useI18n();
  const faqs = [1, 2, 3, 4, 5, 6, 7].map((n) => ({
    q: t(`help.faq${n}q`),
    a: t(`help.faq${n}a`),
  }));
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("help.faq")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2">
            {faqs.map((f) => (
              <details
                key={f.q}
                className="group rounded-md border border-border px-3.5 py-2.5 transition-colors open:bg-bg-subtle/50"
              >
                <summary className="cursor-pointer list-none text-[13px] font-medium text-fg outline-none focus-visible:underline [&::-webkit-details-marker]:hidden">
                  {f.q}
                </summary>
                <p className="mt-1.5 text-footnote leading-relaxed text-fg-muted">{f.a}</p>
              </details>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("help.contact")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2.5 text-[13px]">
            <Mail size={15} strokeWidth={1.75} className="shrink-0 text-fg-subtle" aria-hidden />
            <a
              href={`mailto:${t("help.contactEmail")}`}
              className="font-medium text-accent hover:underline"
            >
              {t("help.contactEmail")}
            </a>
            <span className="text-fg-subtle">{t("help.contactResponse")}</span>
          </div>
        </CardContent>
      </Card>
    </>
  );
}

/** Route /help: SimplePage (provider) + konten. */
export default function HelpPage() {
  return (
    <SimplePage title="help.title" subtitle="help.subtitle">
      <HelpContent />
    </SimplePage>
  );
}
