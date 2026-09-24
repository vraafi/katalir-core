"use client";

import { useState } from "react";
import { SimplePage } from "@/components/SimplePage";

const DATE = "24 September 2026";
const DOMAIN = "https://proyek-agent.pages.dev";
const EMAIL = "support@proyek-agent.pages.dev";
const ADDRESS = "Jakarta, Indonesia";
type Language = "id" | "en";
type LegalKind = "privacy" | "terms";

const privacy = {
  id: {
    title: "Kebijakan Privasi",
    intro: "Katalir menghormati privasi Anda. Kebijakan ini menjelaskan bagaimana kami mengumpulkan, menggunakan, menyimpan, dan melindungi data Anda.",
    sections: [
      ["Pendahuluan", `Kebijakan ini berlaku untuk ${DOMAIN}.`],
      ["Data yang Kami Kumpulkan", "Kami mengumpulkan nama, email, foto profil Google OAuth, ID pengguna Supabase, preferensi bahasa dan tema. Kami menyimpan riwayat chat, workflow, hasil eksekusi, metadata teknis, serta token integrasi Telegram, Google Sheets, Slack, atau HTTP. Token integrasi disimpan terenkripsi dengan Fernet; kunci enkripsi tidak pernah dikirim ke model AI. Kami tidak menyimpan detail kartu kredit; pembayaran diproses Dodo Payments."],
      ["Bagaimana Kami Menggunakan Data", "Kami menggunakan data untuk menjalankan AI agent, mengirim permintaan ke LLM provider yang dipilih, menyimpan riwayat, memproses pembayaran, meningkatkan layanan dengan analytics anonim, dan mengirim notifikasi penting. Kami tidak melatih model sendiri, menjual data, atau menyajikan iklan pihak ketiga."],
      ["Data yang Dibagikan", "Kami membagikan data minimum kepada Google Gemini, Groq, NVIDIA, Supabase, Cloudflare, dan Dodo Payments sesuai fungsi masing-masing. Kami tidak menjual data kepada pihak ketiga."],
      ["Google API Limited Use", "Penggunaan data Google API mengikuti Google API Services User Data Policy dan Limited Use. Kami hanya mengakses Sheets yang Anda izinkan, tidak menggunakan data untuk iklan, dan tidak mengizinkan manusia membacanya kecuali dengan izin eksplisit, untuk keamanan, atau diwajibkan hukum."],
      ["Keamanan Data", "Kredensial integrasi terenkripsi, koneksi memakai HTTPS/TLS, RLS Supabase aktif, service role key tidak diekspos ke client, dan akses sensitif memiliki audit log."],
      ["Retensi Data", "Data akun disimpan selama akun aktif; chat dan workflow sampai Anda menghapus atau akun dihapus; log eksekusi 90 hari; data billing 7 tahun untuk kewajiban pajak."],
      ["Hak Anda", "Anda berhak mengakses, mengekspor, menghapus, mengoreksi, mencabut OAuth, dan keberatan. Penghapusan akun tersedia melalui /settings; data dihapus permanen dalam 30 hari."],
      ["Cookie", "Kami memakai cookie untuk sesi Supabase, preferensi tema/bahasa, dan analytics anonim. Tidak ada cookie tracking pihak ketiga."],
      ["Anak di Bawah Umur", "Katalir tidak ditujukan untuk anak di bawah 13 tahun dan tidak dengan sengaja mengumpulkan data mereka."],
      ["Perubahan Kebijakan", "Perubahan signifikan diberitahukan melalui email atau banner aplikasi."],
      ["Kontak", `Email: ${EMAIL}. Alamat: ${ADDRESS}.`],
      ["Hukum", "Hukum Republik Indonesia, termasuk UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi."],
    ],
  },
  en: {
    title: "Privacy Policy",
    intro: "Katalir respects your privacy. This policy explains how we collect, use, store, and protect your data.",
    sections: [
      ["Introduction", `This policy applies to ${DOMAIN}.`],
      ["Data We Collect", "We collect name, email, Google profile picture, Supabase user ID, language and theme preferences. We store chat history, workflows, execution results, technical metadata, and integration tokens for Telegram, Google Sheets, Slack, or HTTP. Tokens are encrypted with Fernet; encryption keys are never sent to AI models. We do not store card details; Dodo Payments processes payments."],
      ["How We Use Your Data", "We use data to run the AI agent, send requests to the selected LLM provider, retain history, process payments, improve the service with anonymous analytics, and send important notices. We do not train our own models, sell data, or serve third-party advertising."],
      ["Data Sharing", "We share minimum necessary data with Google Gemini, Groq, NVIDIA, Supabase, Cloudflare, and Dodo Payments for their respective functions. We do not sell data to third parties."],
      ["Google API Limited Use", "Use of Google API data follows the Google API Services User Data Policy and Limited Use. We access only authorized Sheets, do not use data for advertising, and do not allow human access except with explicit permission, security need, or legal requirement."],
      ["Data Security", "Integration credentials are encrypted, connections use HTTPS/TLS, Supabase RLS is enabled, service role keys are not exposed to clients, and sensitive access is audited."],
      ["Data Retention", "Account data remains while active; chats and workflows until deletion; execution logs for 90 days; billing data for 7 years for tax obligations."],
      ["Your Rights", "You may access, export, delete, correct, revoke OAuth access, and object. Account deletion is at /settings; data is permanently deleted within 30 days."],
      ["Cookies", "We use cookies for Supabase login, theme/language preferences, and anonymous analytics. No third-party tracking cookies."],
      ["Children", "Katalir is not intended for children under 13 and does not knowingly collect their data."],
      ["Policy Changes", "Significant changes will be announced by email or an in-app banner."],
      ["Contact", `Email: ${EMAIL}. Address: ${ADDRESS}.`],
      ["Governing Law", "Laws of the Republic of Indonesia, including Law No. 27 of 2022 on Personal Data Protection."],
    ],
  },
} as const;


const terms = {
  id: {
    title: "Syarat dan Ketentuan Layanan",
    intro: "Dengan mengakses atau menggunakan Katalir, Anda setuju terikat oleh syarat dan ketentuan ini.",
    sections: [
      ["Penerimaan Syarat", "Jika Anda tidak setuju, jangan gunakan layanan."],
      ["Deskripsi Layanan", "Katalir adalah layanan SaaS untuk membangun AI agent tanpa coding. Anda menjelaskan kebutuhan, lalu AI menyusun, menjalankan, dan melaporkan workflow."],
      ["Akun Anda", "Anda harus berusia minimal 13 tahun, menjaga kerahasiaan kredensial, bertanggung jawab atas aktivitas akun, dan dapat ditangguhkan jika melanggar syarat."],
      ["Penggunaan yang Dapat Diterima", "Dilarang menggunakan layanan untuk spam, aktivitas ilegal, reverse engineering, scraping, akses akun lain, serangan API/DoS, malware, phishing, pelanggaran IP, atau konten melanggar hukum."],
      ["Pembayaran dan Langganan", "Paket Plus $299 USD per tahun, diproses Dodo Payments, diperpanjang otomatis, dapat dibatalkan melalui /billing, dan mengikuti kebijakan refund Dodo."],
      ["Kekayaan Intelektual", "Kode, brand, logo, dan UI adalah milik kami. Workflow, chat, dan konten Anda tetap milik Anda. Kami tidak mengklaim output AI; Anda memberi lisensi terbatas untuk pemrosesan sesuai Kebijakan Privasi."],
      ["Ketersediaan Layanan", "Kamipea 99%+ uptime, tanpa menjamin 100%. Maintenance dan downtime pihak ketiga di luar kendali kami."],
      ["Disclaimer", "Layanan diberikan as is dan as available. Output AI dan integrasi pihak ketiga tidak dijamin selalu akurat atau tersedia."],
      ["Batasan Tanggung Jawab", "Sejauh diizinkan hukum, tanggung jawab kami dibatasi total biaya langganan tahunan dan tidak mencakup kerugian tidak langsung atau konsekuensial."],
      ["Penghentian", "Anda dapat berhenti melalui /settings. Data dihapus dalam 30 hari; kewajiban pembayaran jatuh tempo tetap berlaku."],
      ["Perubahan Syarat", "Perubahan signifikan diberitahukan melalui email atau aplikasi."],
      ["Hukum", "Hukum Republik Indonesia; sengketa melalui pengadilan Indonesia."],
      ["Kontak", `Email: ${EMAIL}. Alamat: ${ADDRESS}.`],
    ],
  },
  en: {
    title: "Terms of Service",
    intro: "By accessing or using Katalir, you agree to these Terms of Service.",
    sections: [
      ["Acceptance of Terms", "If you do not agree, do not use the service."],
      ["Service Description", "Katalir is a SaaS service for building AI agents without coding. Describe your needs; the AI builds, runs, and reports workflows."],
      ["Your Account", "You must be at least 13, keep credentials confidential, are responsible for account activity, and may be suspended for violating these terms."],
      ["Acceptable Use", "Do not use the service for spam, illegal activity, reverse engineering, scraping, unauthorized account access, API abuse or DoS, malware, phishing, IP violations, or unlawful content."],
      ["Payment and Subscription", "The Plus plan is $299 USD per year, processed by Dodo Payments, auto-renews, can be cancelled at /billing, and follows Dodo's refund policy."],
      ["Intellectual Property", "Katalir code, brand, logo, and UI belong to us. Your workflows, chats, and content remain yours. We do not claim AI outputs; you grant a limited processing license under the Privacy Policy."],
      ["Service Availability", "We aim for 99%+ uptime but do not guarantee 100%. Maintenance and third-party downtime are outside our control."],
      ["Disclaimer", "The service is provided as is and as available. AI output and third-party integrations are not guaranteed accurate or available."],
      ["Limitation of Liability", "Liability is limited to your total annual subscription fee and excludes indirect or consequential damages."],
      ["Termination", "You may terminate at /settings. Data is deleted within 30 days; outstanding payment obligations remain."],
      ["Changes to Terms", "Significant changes will be announced by email or in-app."],
      ["Governing Law", "Indonesian law; disputes go through Indonesian courts."],
      ["Contact", `Email: ${EMAIL}. Address: ${ADDRESS}.`],
    ],
  },
} as const;


const CONTENT: Record<LegalKind, typeof privacy> = { privacy, terms: terms as unknown as typeof privacy };

export default function LegalPage({ kind }: { kind: LegalKind }) {
  const [lang, setLang] = useState<Language>("id");
  const copy = CONTENT[kind][lang];
  return <SimplePage title={copy.title} subtitle={`Terakhir diperbarui / Last updated: ${DATE}`} maxW="max-w-3xl">
    <div className="flex gap-2" role="group" aria-label="Language">
      <button type="button" onClick={() => setLang("id")} aria-pressed={lang === "id"} className={`rounded-md border px-3 py-2 text-sm ${lang === "id" ? "border-accent bg-accent/10 text-accent" : "border-border"}`}>Bahasa Indonesia</button>
      <button type="button" onClick={() => setLang("en")} aria-pressed={lang === "en"} className={`rounded-md border px-3 py-2 text-sm ${lang === "en" ? "border-accent bg-accent/10 text-accent" : "border-border"}`}>English</button>
    </div>
    <p className="rounded-lg border border-border bg-bg-subtle/40 p-4 text-sm leading-relaxed text-fg-muted">{copy.intro}</p>
    {copy.sections.map(([heading, body]) => <section key={heading}><h2 className="text-base font-semibold">{heading}</h2><p className="mt-1 text-sm leading-relaxed text-fg-muted">{body}</p></section>)}
    <nav className="flex flex-wrap gap-3 border-t border-border pt-5 text-sm"><a href="/privacy" className="text-accent hover:underline">Privacy Policy</a><a href="/terms" className="text-accent hover:underline">Terms of Service</a></nav>
  </SimplePage>;
}
