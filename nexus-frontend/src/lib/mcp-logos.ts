/**
 * MCP app logo data.
 *
 * Two sources, and why both are needed:
 *  - `@lobehub/icons` for the 40 brands it actually ships (GitHub, Google,
 *    Vercel, Notion, Railway, Figma, Anthropic, OpenAI, Cloudflare, N8n,
 *    Zapier, MCP, DeepSeek, Gemini, Groq, Ollama, Replicate, HuggingFace, ...).
 *    Verified against the package's own directory listing: it is 38 MB and is
 *    mostly AI-model logos, with no Slack, Stripe, Linear, Supabase, Discord or
 *    Telegram at all.
 *  - Baked brand paths in `brand-paths.ts` for the 15 it does not ship. These
 *    are inlined rather than hot-linked from cdn.simpleicons.org because the
 *    production CSP is `img-src 'self' data: blob:`, which blocked every remote
 *    logo at runtime.
 */
import {
  Ai302, Anthropic, Aws, Azure, Baidu, Brave, Cline, Cloudflare, CodeFlicker,
  Cursor, DeepSeek, DigitalOcean, Exa, Figma, Gemini, Github, GithubCopilot,
  Glama, Google, GoogleCloud, Groq, HuggingFace, MCP, Mistral, N8n,
  Notion, Nvidia, Ollama, OpenAI, Perplexity, Railway, Replicate, Replit,
  Smithery, Tavily, Together, V0, Vercel, Windsurf, Zapier,
} from "@lobehub/icons";
import { BRAND_PATHS } from "./brand-paths";

export type McpLogo = {
  name: string;
  /** Local component when lobehub ships the brand. Its own `CompoundedIcon`
   *  type is stricter than a plain function component, so this stays ElementType. */
  Component?: React.ElementType;
  /** Baked brand path for the brands lobehub does not ship at all. */
  path?: { viewBox: string; d: string };
};

export const mcpLogos: McpLogo[] = [
  { name: "GitHub", Component: Github },
  { name: "Slack", path: brandPath("slack") },
  { name: "Notion", Component: Notion },
  { name: "Linear", path: brandPath("linear") },
  { name: "Stripe", path: brandPath("stripe") },
  { name: "Supabase", path: brandPath("supabase") },
  { name: "Vercel", Component: Vercel },
  { name: "Figma", Component: Figma },
  { name: "Discord", path: brandPath("discord") },
  { name: "Telegram", path: brandPath("telegram") },
  { name: "Google", Component: Google },
  { name: "AWS", Component: Aws },
  { name: "Cloudflare", Component: Cloudflare },
  { name: "Docker", path: brandPath("docker") },
  { name: "GitLab", path: brandPath("gitlab") },
  { name: "Postgres", path: brandPath("postgresql") },
  { name: "Redis", path: brandPath("redis") },
  { name: "MongoDB", path: brandPath("mongodb") },
  { name: "Airtable", path: brandPath("airtable") },
  { name: "Zoom", path: brandPath("zoom") },
  { name: "Shopify", path: brandPath("shopify") },
  { name: "Sentry", path: brandPath("sentry") },
  { name: "Railway", Component: Railway },
  { name: "DigitalOcean", Component: DigitalOcean },
  { name: "Replicate", Component: Replicate },
  { name: "Hugging Face", Component: HuggingFace },
  { name: "Anthropic", Component: Anthropic },
  { name: "OpenAI", Component: OpenAI },
  { name: "DeepSeek", Component: DeepSeek },
  { name: "Gemini", Component: Gemini },
  { name: "Mistral", Component: Mistral },
  { name: "Groq", Component: Groq },
  { name: "Perplexity", Component: Perplexity },
  { name: "Ollama", Component: Ollama },
  { name: "Together", Component: Together },
  { name: "Replit", Component: Replit },
  { name: "Cursor", Component: Cursor },
  { name: "Cline", Component: Cline },
  { name: "Windsurf", Component: Windsurf },
  { name: "Copilot", Component: GithubCopilot },
  { name: "Brave Search", Component: Brave },
  { name: "Tavily", Component: Tavily },
  { name: "Exa", Component: Exa },
  { name: "N8n", Component: N8n },
  { name: "Zapier", Component: Zapier },
  { name: "MCP", Component: MCP },
  { name: "Glama", Component: Glama },
  { name: "Smithery", Component: Smithery },
  { name: "Azure", Component: Azure },
  { name: "Google Cloud", Component: GoogleCloud },
  { name: "Nvidia", Component: Nvidia },
  { name: "302.AI", Component: Ai302 },
  { name: "Baidu", Component: Baidu },
  { name: "CodeFlicker", Component: CodeFlicker },
  { name: "v0", Component: V0 },
];

/** Maps a Simple Icons slug to its baked path. */
export function brandPath(slug: string) {
  return BRAND_PATHS[slug];
}
