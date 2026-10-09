/**
 * Klien API untuk fitur Connector Health (FASE 2/3/6).
 *
 * Endpoint-endpoint ini **publik-baca** (katalog connector bersifat global),
 * jadi tidak memerlukan JWT. Tetap memakai `apiFetch` agar base URL dan
 * header konsisten dengan fitur lain.
 */
import { apiFetch } from "@/lib/api";
import type {
  ConnectorHealthList,
  ConnectorHealthSchema,
  ConnectorHealthSummary,
  ConnectorVerdict,
} from "./types";

export class ConnectorHealthError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ConnectorHealthError";
    this.status = status;
  }
}

async function readError(
  res: Response,
  fallback: string,
): Promise<ConnectorHealthError> {
  let detail = "";
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") detail = body.detail;
  } catch {
    /* body bukan JSON */
  }
  return new ConnectorHealthError(
    detail || `${fallback} (${res.status})`,
    res.status,
  );
}

/** GET /connectors/health — ringkasan verdict dari probe live. */
export async function getHealthSummary(): Promise<ConnectorHealthSummary> {
  const res = await apiFetch("/connectors/health");
  if (!res.ok) throw await readError(res, "Gagal memuat ringkasan kesehatan");
  return (await res.json()) as ConnectorHealthSummary;
}

/** GET /connectors/health/schema — kontrak prober + repair. */
export async function getHealthSchema(): Promise<ConnectorHealthSchema> {
  const res = await apiFetch("/connectors/health/schema");
  if (!res.ok) throw await readError(res, "Gagal memuat skema prober");
  return (await res.json()) as ConnectorHealthSchema;
}

/** GET /connectors/health/{verdict}/list — daftar konektor per verdict. */
export async function listByVerdict(
  verdict: ConnectorVerdict,
  limit = 100,
): Promise<ConnectorHealthList> {
  const res = await apiFetch(
    `/connectors/health/${encodeURIComponent(verdict)}/list?limit=${limit}`,
  );
  if (!res.ok) throw await readError(res, "Gagal memuat daftar konektor");
  return (await res.json()) as ConnectorHealthList;
}
