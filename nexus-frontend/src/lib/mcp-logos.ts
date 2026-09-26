/**
 * MCP app logo data.
 *
 * Sources, and why both are used:
 *  - `@lobehub/icons` for the brands it actually ships (GitHub, Google, Vercel,
 *    Notion, Railway, Figma, Anthropic, OpenAI, Cloudflare, N8n, Zapier, MCP,
 *    DeepSeek, Gemini, Groq, Ollama, Replicate, HuggingFace, ...). Verified by
 *    reading the package's own directory listing - it is 38 MB and mostly
 *    AI-model logos.
 *  - Simple Icons CDN for the brands lobehub does not ship at all (Slack,
 *    Stripe, Linear, Supabase, Discord, Telegram, GitLab, Postgres, Redis,
 *    Docker, Sentry, Airtable, Zoom, Shopify, ...). That is the documented
 *    fallback, and it is the only way to reach 40+ real integrations without
 *    inlining 40+ hand-written SVGs.
 */
import {
  Ai302, Anthropic, Aws, Azure, Baidu, Brave, Cline, Cloudflare, CodeFlicker,
  Cursor, DeepSeek, DigitalOcean, Exa, Figma, Gemini, Github, GithubCopilot,
  Glama, Google, GoogleCloud, Groq, HuggingFace, MCP, Mistral, N8n,
  Notion, Nvidia, Ollama, OpenAI, Perplexity, Railway, Replicate, Replit,
  Smithery, Tavily, Together, V0, Vercel, Windsurf, Zapier,
} from "@lobehub/icons";

export type McpLogo = {
  name: string;
  /** Local component when lobehub ships the brand. Its own `CompoundedIcon`
   *  type is stricter than a plain function component, so this stays ElementType. */
  Component?: React.ElementType;
  /** Simple Icons slug when lobehub does not ship the brand. */
  slug?: string;
};

export const mcpLogos: McpLogo[] = [
  { name: "GitHub", Component: Github },
  { name: "Slack", slug: "slack" },
  { name: "Notion", Component: Notion },
  { name: "Linear", slug: "linear" },
  { name: "Stripe", slug: "stripe" },
  { name: "Supabase", slug: "supabase" },
  { name: "Vercel", Component: Vercel },
  { name: "Figma", Component: Figma },
  { name: "Discord", slug: "discord" },
  { name: "Telegram", slug: "telegram" },
  { name: "Google", Component: Google },
  { name: "AWS", Component: Aws },
  { name: "Cloudflare", Component: Cloudflare },
  { name: "Docker", slug: "docker" },
  { name: "GitLab", slug: "gitlab" },
  { name: "Postgres", slug: "postgresql" },
  { name: "Redis", slug: "redis" },
  { name: "MongoDB", slug: "mongodb" },
  { name: "Airtable", slug: "airtable" },
  { name: "Zoom", slug: "zoom" },
  { name: "Shopify", slug: "shopify" },
  { name: "Sentry", slug: "sentry" },
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

/** Simple Icons CDN URL. The brand colour is applied by CSS filter, so the
 *  request itself stays cacheable and theme-neutral. */
export function simpleIconUrl(slug: string): string {
  return `https://cdn.simpleicons.org/${slug}/919191`;
}
