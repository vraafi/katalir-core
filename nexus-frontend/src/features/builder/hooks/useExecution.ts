import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

export interface ExecutionLog {
  step_kind?: string;
  node_id?: string;
  status?: string;
  payload?: { reply?: string; instruction?: string; result?: string; message?: string; [k: string]: unknown };
}

interface ExecuteResponse {
  execution_id?: string;
  status?: string;
  data?: { execution_id?: string };
}

/** POST /workflows/{id}/execute — fire-and-return execution_id (202). */
export function useExecuteMutation() {
  return useMutation<ExecuteResponse, Error, { workflowId: string }>({
    mutationFn: async ({ workflowId }) => {
      const res = await apiFetch(`/workflows/${workflowId}/execute`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (res.status !== 202) throw new Error("HTTP " + res.status);
      return await res.json();
    },
  });
}

/**
 * Polling runner for execution logs (2 detik, sampai terminal state).
 * Returns live status/logs + start/stop — no manual setInterval in component.
 */
export function useExecutionPolling() {
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  function stop() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function pollOnce(id: string) {
    try {
      const r = await apiFetch(`/executions/${id}`);
      if (!r.ok) return;
      const d = await r.json();
      const execution = d?.execution ?? d;
      const st = execution?.status ?? d?.status ?? null;
      if (st) setStatus(st);
      const fetched = d?.logs ?? execution?.logs ?? [];
      if (Array.isArray(fetched) && fetched.length > 0) setLogs(fetched);
      if (st === "completed" || st === "failed" || st === "error") {
        stop();
        setLogs((prev) => [...prev, { step_kind: "system", status: st === "completed" ? "ok" : "error", payload: { message: `Eksekusi selesai: ${st}` } }]);
      }
    } catch {
      /* coba lagi pada interval berikutnya */
    }
  }

  function start(id: string) {
    setLogs([]);
    setStatus("pending");
    setOpen(true);
    setLogs([{ step_kind: "system", status: "ok", payload: { message: `Memonitor execution_id: ${id}` } }]);
    stop();
    pollRef.current = setInterval(() => { void pollOnce(id); }, 2000);
    void pollOnce(id);
  }

  return { start, stop, status, logs, setStatus, setLogs, open, setOpen };
}