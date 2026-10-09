/**
 * Tipe untuk fitur Connector Health (FASE 2/3/6).
 *
 * Angka di sini berasal dari **probe live** yang tersimpan di tabel
 * `connector_health` — bukan dari metadata katalog. Lihat
 * docs/audit/connector-connection-honest-audit.md untuk alasan pemisahan ini.
 */

export type ConnectorVerdict = "ALIVE" | "AUTH" | "DEAD" | "UNKNOWN";

export interface ConnectorHealthCounts {
  ALIVE: number;
  AUTH: number;
  DEAD: number;
  UNKNOWN: number;
  total: number;
}

export interface ConnectorHealthRecord {
  connector_id: string;
  endpoint_url: string | null;
  verdict: ConnectorVerdict;
  http_status: number | null;
  tools_count: number | null;
  latency_ms: number | null;
  error: string | null;
  prober: string | null;
  checked_at: string;
}

export interface CatalogCounts {
  total: number | null;
  executable: number | null;
  metadata_only: number | null;
}

export interface ConnectorHealthSummary {
  status: string;
  health: ConnectorHealthCounts;
  catalog: CatalogCounts;
  store: {
    db_available: boolean;
    activation_rows: number;
    health: ConnectorHealthCounts;
    tables: string[];
  };
}

export interface ConnectorHealthList {
  status: string;
  verdict: ConnectorVerdict;
  count: number;
  connectors: ConnectorHealthRecord[];
}

export interface ConnectorHealthSchema {
  status: string;
  prober: {
    protocol_version: string;
    timeout_s: number;
    workers: number;
    supported_transports: string[];
    verdicts: string[];
  };
  repair: {
    max_rounds: number;
    backoff_s: number[];
    hard_stops: string[];
    methodology_from: string;
    statuses: string[];
  };
  verdicts: string[];
}
