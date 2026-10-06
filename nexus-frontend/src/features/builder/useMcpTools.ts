"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

/** Satu tool MCP seperti yang dipulangkan `GET /mcp/gateway/servers`. */
export type McpGatewayTool = {
  name: string;
  title?: string;
  description?: string;
};

export type McpToolsState = "idle" | "loading" | "ready" | "error";

/**
 * Katalog tool MCP dari agentgateway.
 *
 * KENAPA ENDPOINT-NYA `/mcp/gateway/servers` DAN BUKAN `/mcp/gateway/tools`:
 * brief menyebut `/api/mcp/gateway/tools`, tetapi path itu **tidak ada** di
 * backend (`api_server.py` hanya punya `/mcp/gateway/health`, `/servers`,
 * `/call`). `/servers` membalas `{"tools":[{name,title,description,inputSchema}]}`
 * — itulah daftar tool yang dipakai. `apiFetch` dipakai supaya JWT + API_URL +
 * timeout konsisten dengan halaman lain; `fetch('/api/...')` akan menembak
 * origin frontend (Cloudflare Pages), bukan FastAPI.
 *
 * KENAPA ADA CACHE: gateway meneruskan `initialize` ke SEMUA target stdio
 * (npx/uvx) yang cold-start — terukur 13 detik di produksi. Panel konfigurasi
 * di-mount ulang setiap kali node dipilih, jadi tanpa cache setiap klik node
 * MCP akan memicu fetch 13 detik lagi.
 */
const TIMEOUT_MS = 30_000;
const TTL_MS = 5 * 60_000;

let _cache: { at: number; tools: McpGatewayTool[] } | null = null;

/** Hanya untuk test: buang cache modul. */
export function __resetMcpToolsCache() {
  _cache = null;
}

export function useMcpTools(enabled: boolean) {
  const [tools, setTools] = useState<McpGatewayTool[]>(() => _cache?.tools ?? []);
  const [state, setState] = useState<McpToolsState>(enabled ? "loading" : "idle");
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async (force = false) => {
    if (!force && _cache && Date.now() - _cache.at < TTL_MS) {
      setTools(_cache.tools);
      setState("ready");
      return;
    }
    setState("loading");
    try {
      const r = await apiFetch("/mcp/gateway/servers", { timeoutMs: TIMEOUT_MS });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as { tools?: McpGatewayTool[] };
      const list = (Array.isArray(data.tools) ? data.tools : []).filter(
        (t): t is McpGatewayTool => Boolean(t && typeof t.name === "string" && t.name),
      );
      _cache = { at: Date.now(), tools: list };
      if (!alive.current) return;
      setTools(list);
      setState("ready");
    } catch {
      if (!alive.current) return;
      setTools([]);
      setState("error");
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setState("idle");
      return;
    }
    void load();
  }, [enabled, load]);

  return { tools, state, reload: () => load(true) };
}
