/**
 * MCP app logo data — colour-accurate since F6.
 *
 * WHY NOT JUST USE ONE ICON PACK (measured, not assumed):
 *
 * 1. `@lobehub/icons@5.21.0` has **no `.Color` variant**. Its compounded icons
 *    export `Mono`, `Avatar`, `Combine` and `Text` only, so the suggested
 *    `<Github.Color />` fallback does not exist in this version. Verified
 *    against the package's own the es/<icon>/components directories directories: zero of them
 *    contain a `Color` component.
 *
 * 2. `@icons-pack/react-simple-icons` covers most brands, but Simple Icons
 *    v16 REMOVED Slack, OpenAI, Amazon AWS, Twilio and Heroku for trademark
 *    reasons. `SiSlackware` is a Linux distribution, NOT Slack the chat app —
 *    mapping Slack to it would put a penguin on the landing page under Slack's
 *    name. That is precisely the plausible-looking wrong this project's whole
 *    verification tier exists to prevent, so every `Si*` name below was checked
 *    against the package's real `index.d.ts` rather than trusted.
 *
 * Three tiers, and every brand lands in exactly one:
 *
 *   simple-icons  — the true brand fill, via `color="default"`.
 *   lobehub Mono  — tinted with the icon's own `colorPrimary`, which is the
 *                   brand colour lobehub ships, not one we invented.
 *   baked path    — `currentColor`, plus an explicit hex only where the brand's
 *                   own documented primary colour is known.
 *
 * The two older sources are still needed: lobehub is mostly AI-model logos, and
 * the baked paths cover what neither package ships.
 */
import {
  Ai302, Anthropic, Azure, Aws, Baidu, Brave, Cline, Cloudflare, CodeFlicker,
  Cursor, DeepSeek, DigitalOcean, Exa, Figma, Gemini, Github, GithubCopilot,
  Glama, Google, GoogleCloud, Groq, HuggingFace, MCP, Mistral, N8n,
  Notion, Nvidia, Ollama, OpenAI, Perplexity, Railway, Replicate, Replit,
  Smithery, Tavily, Together, V0, Vercel, Windsurf, Zapier,
} from "@lobehub/icons";
import {
  SiGithub, SiNotion, SiVercel, SiFigma, SiGoogle, SiCloudflare,
  SiDigitalocean, SiRailway, SiAnthropic, SiHuggingface, SiReplicate,
  SiPerplexity, SiOllama, SiReplit, SiMistralai, SiDeepseek,
  SiGooglegemini, SiGithubcopilot, SiLinear, SiStripe, SiSupabase,
  SiDiscord, SiTelegram, SiDocker, SiGitlab, SiPostgresql, SiRedis,
  SiMongodb, SiAirtable, SiZoom, SiShopify, SiSentry,
} from "@icons-pack/react-simple-icons";
import { BRAND_PATHS } from "./brand-paths";

/** Ask simple-icons for the real brand fill instead of a theme colour. */
const BRAND = "default" as const;

export type McpLogo = {
  name: string;
  /** Local component: a simple-icons icon or a lobehub Mono icon. lobehub's
   *  `CompoundedIcon` type is stricter than a plain function component, so this
   *  stays ElementType. */
  Component?: React.ElementType;
  /** Baked brand path for the brands neither package ships. */
  path?: { viewBox: string; d: string };
  /** `"default"` for simple-icons. A hex for a lobehub icon with no
   *  simple-icons twin, read from that icon's own `colorPrimary`. */
  color?: string;
};

/** lobehub's own brand colour for an icon, or undefined when it has none.
 *
 * A near-white `colorPrimary` is treated as "no colour in this theme" and
 * deliberately returns undefined, so the tile falls back to the theme
 * foreground. Six icons ship `#FFFFFF` - Together, Windsurf, Tavily, MCP,
 * Azure and Google Cloud - and on a light surface that is not a subtle
 * rendering choice, it is a logo painted white on white: genuinely invisible.
 * Those brand primaries are correct for a dark UI and simply do not transfer,
 * so the honest move is to fall back rather than reproduce a white logo.
 */
function lobe<T extends { colorPrimary?: string }>(Icon: T): string | undefined {
  const hex = Icon?.colorPrimary;
  if (!hex || !/^#[0-9a-f]{6}$/i.test(hex)) return undefined;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(1 + i, 3 + i), 16));
  // Relative luminance, sRGB coefficients. 0.78 is comfortably above "light
  // background" and comfortably below "readable ink".
  const lin = [r, g, b].map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  const luminance = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  if (luminance > 0.78) return undefined;
  return hex;
}


export const mcpLogos: McpLogo[] = [
  { name: "GitHub", Component: SiGithub, color: BRAND },
  { name: "Slack", path: brandPath("slack"), color: "#4A154B" },
  { name: "Notion", Component: SiNotion, color: BRAND },
  { name: "Linear", Component: SiLinear, color: BRAND },
  { name: "Stripe", Component: SiStripe, color: BRAND },
  { name: "Supabase", Component: SiSupabase, color: BRAND },
  { name: "Vercel", Component: SiVercel, color: BRAND },
  { name: "Figma", Component: SiFigma, color: BRAND },
  { name: "Discord", Component: SiDiscord, color: BRAND },
  { name: "Telegram", Component: SiTelegram, color: BRAND },
  { name: "Google", Component: SiGoogle, color: BRAND },
  { name: "AWS", Component: Aws, color: lobe(Aws) },
  { name: "Cloudflare", Component: SiCloudflare, color: BRAND },
  { name: "Docker", Component: SiDocker, color: BRAND },
  { name: "GitLab", Component: SiGitlab, color: BRAND },
  { name: "Postgres", Component: SiPostgresql, color: BRAND },
  { name: "Redis", Component: SiRedis, color: BRAND },
  { name: "MongoDB", Component: SiMongodb, color: BRAND },
  { name: "Airtable", Component: SiAirtable, color: BRAND },
  { name: "Zoom", Component: SiZoom, color: BRAND },
  { name: "Shopify", Component: SiShopify, color: BRAND },
  { name: "Sentry", Component: SiSentry, color: BRAND },
  { name: "Railway", Component: SiRailway, color: BRAND },
  { name: "DigitalOcean", Component: SiDigitalocean, color: BRAND },
  { name: "Replicate", Component: SiReplicate, color: BRAND },
  { name: "Hugging Face", Component: SiHuggingface, color: BRAND },
  { name: "Anthropic", Component: SiAnthropic, color: BRAND },
  { name: "OpenAI", Component: OpenAI, color: lobe(OpenAI) },
  { name: "DeepSeek", Component: SiDeepseek, color: BRAND },
  { name: "Gemini", Component: SiGooglegemini, color: BRAND },
  { name: "Mistral", Component: SiMistralai, color: BRAND },
  { name: "Groq", Component: Groq, color: lobe(Groq) },
  { name: "Perplexity", Component: SiPerplexity, color: BRAND },
  { name: "Ollama", Component: SiOllama, color: BRAND },
  { name: "Together", Component: Together, color: lobe(Together) },
  { name: "Replit", Component: SiReplit, color: BRAND },
  { name: "Cursor", Component: Cursor, color: lobe(Cursor) },
  { name: "Cline", Component: Cline, color: lobe(Cline) },
  { name: "Windsurf", Component: Windsurf, color: lobe(Windsurf) },
  { name: "Copilot", Component: SiGithubcopilot, color: BRAND },
  { name: "Brave Search", Component: Brave, color: lobe(Brave) },
  { name: "Tavily", Component: Tavily, color: lobe(Tavily) },
  { name: "Exa", Component: Exa, color: lobe(Exa) },
  { name: "N8n", Component: N8n, color: lobe(N8n) },
  { name: "Zapier", Component: Zapier, color: lobe(Zapier) },
  { name: "MCP", Component: MCP, color: lobe(MCP) },
  { name: "Glama", Component: Glama, color: lobe(Glama) },
  { name: "Smithery", Component: Smithery, color: lobe(Smithery) },
  { name: "Azure", Component: Azure, color: lobe(Azure) },
  { name: "Google Cloud", Component: GoogleCloud, color: lobe(GoogleCloud) },
  { name: "Nvidia", Component: Nvidia, color: lobe(Nvidia) },
  { name: "302.AI", Component: Ai302, color: lobe(Ai302) },
  { name: "Baidu", Component: Baidu, color: lobe(Baidu) },
  { name: "CodeFlicker", Component: CodeFlicker, color: lobe(CodeFlicker) },
  { name: "v0", Component: V0, color: lobe(V0) },
];

/** Maps a Simple Icons slug to its baked path. */
export function brandPath(slug: string) {
  return BRAND_PATHS[slug];
}

/**
 * The short list that goes in the hero.
 *
 * Why a subset exists at all: 55 tiles in an 8-column grid is roughly 450px of
 * logo, which does not belong above the fold. It would push the headline and
 * the CTA down, and those are the one thing on this page that must not be
 * pushed down. So the hero gets the most recognisable brands on a single row,
 * and the full cloud stays below the fold where it can be as large as it likes.
 */
export const heroLogos: McpLogo[] = mcpLogos.filter((l) =>
  ["GitHub", "Slack", "Notion", "Stripe", "Vercel", "Google", "Anthropic", "OpenAI", "Docker", "Cloudflare"].includes(l.name),
);
