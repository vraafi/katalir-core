import { test, expect } from "@playwright/test";
import { buildExecutionReport } from "../src/features/agent/execution-report";

/**
 * `execution-report.ts` adalah fungsi murni, jadi diuji langsung di Node
 * oleh Playwright (TS-nya diawetkan) tanpa browser, tanpa deploy, tanpa
 * token auth. Ini mengunci tiga bug nyata yang ditemukan saat wiring:
 *   1. `collapse()` menelan baris retry -> 5 percobaan jadi 1.
 *   2. `statusOf()` menandai "retrying" sebagai "error".
 *   3. `okCount` menghitung baris retry sebagai sukses.
 * Plus: payload healing tidak pernah diteruskan ke step.
 */

/** Bentuk baris `execution_logs` yang ditulis `append_execution_log`. */
function retryLog(attempt: number, max: number, delay: number) {
  return {
    node_id: "a1",
    kind: "node",
    status: "retrying",
    payload: {
      healing: {
        action: "retry",
        node_id: "a1",
        attempt,
        max_attempts: max,
        category: "rate_limit",
        reason: "HTTP 429 dari provider",
        changes: {},
        provider: "openai",
        delay_ms: delay,
        trace: [],
        search_hits: 2,
        suggestions: [{ kind: "forum", text: "Backoff eksponensial", link: "https://example.com/a" }],
      },
    },
  };
}

test.describe("self-healing di execution report", () => {
  // Regresi #1 --TJAGA SENGAJA-: collapse() lama menyimpan hanya baris
  // TERAKHIR per node_id, jadi 5 percobaan jadi 1 baris. MenAssert 1
  // di sini berarti test ini tidak lagi menguji apa pun. Kalau baris ini
  // gagal, itu UMUMNYA bug, bukan test yang salah.
  test("lima percobaan retry tidak digabung jadi satu baris", () => {
    const logs = [
      retryLog(1, 5, 1000),
      retryLog(2, 5, 2000),
      retryLog(3, 5, 4000),
      retryLog(4, 5, 8000),
      retryLog(5, 5, 16000),
      { node_id: "a1", kind: "node", status: "completed", payload: { summary: "ok" } },
    ];
    const r = buildExecutionReport({ logs, status: "completed" } as any);
    const retries = r.steps.filter((s) => s.status === "retrying");
    // Regresi: collapse() lama menyimpan hanya baris TERAKHIR per node_id.
    expect(retries).toHaveLength(5);
  });

  test("retrying bukan error: lima percobaan yang sukses tidak dihitung gagal", () => {
    const logs = [
      retryLog(1, 5, 1000),
      retryLog(2, 5, 2000),
      { node_id: "a1", kind: "node", status: "completed", payload: { summary: "ok" } },
    ];
    const r = buildExecutionReport({ logs, status: "completed" } as any);
    expect(r.failCount).toBe(0);
    expect(r.ok).toBe(true);
    // 1 node sukses, bukan 3.
    expect(r.okCount).toBe(1);
  });

  test("payload healing diteruskan utuh ke step", () => {
    const r = buildExecutionReport({ logs: [retryLog(2, 5, 2000)], status: "running" } as any);
    const step = r.steps.find((s) => s.status === "retrying");
    expect(step?.healing).toBeTruthy();
    expect(step?.healing?.attempt).toBe(2);
    expect(step?.healing?.max_attempts).toBe(5);
    expect(step?.healing?.delay_ms).toBe(2000);
    expect(step?.healing?.provider).toBe("openai");
    expect(step?.healing?.search_hits).toBe(2);
    expect(step?.healing?.suggestions?.[0]?.link).toBe("https://example.com/a");
  });

  test("escalate membawa saran dan dihitung sebagai gagal", () => {
    const esc = {
      node_id: "a1",
      kind: "node",
      status: "error",
      payload: {
        healing: {
          action: "escalate",
          node_id: "a1",
          attempt: 5,
          max_attempts: 5,
          category: "rate_limit",
          reason: "5 percobaan gagal",
          changes: {},
          provider: "openai",
          delay_ms: 0,
          trace: [],
          search_hits: 1,
          suggestions: [{ kind: "forum", text: "Cek kuota API" }],
        },
      },
    };
    const r = buildExecutionReport({ logs: [esc], status: "failed" } as any);
    expect(r.failCount).toBe(1);
    const step = r.steps[0];
    expect(step.healing?.action).toBe("escalate");
    expect(step.healing?.suggestions).toHaveLength(1);
  });

  test("credential: kategori auth tidak di-retry dan saranDisplayed", () => {
    const cred = {
      node_id: "a1",
      kind: "node",
      status: "error",
      payload: {
        healing: {
          action: "credential",
          node_id: "a1",
          attempt: 1,
          max_attempts: 5,
          category: "auth",
          reason: "invalid_grant",
          changes: {},
          provider: "anthropic",
          delay_ms: 0,
          trace: [],
          search_hits: 0,
          suggestions: [{ kind: "fix", text: "Refresh OAuth token" }],
        },
      },
    };
    const r = buildExecutionReport({ logs: [cred], status: "failed" } as any);
    expect(r.steps[0].healing?.action).toBe("credential");
    expect(r.steps[0].healing?.suggestions?.[0]?.text).toBe("Refresh OAuth token");
  });

  // Regresi #4: `collapse()` membuat kunci unik per baris retry, tapi dulu
  // mapper BUANG kunci itu sehingga semua baris retry satu node berbagi
  // `id`. `ExecutionReportCard` memakai `openStep === s.id` (accordion satu
  // jendela) sehingga semua baris itu ikut buka-tutup BERSAMA. Ditemukan
  // saat menulis screenshot: skenario "2 retry" kebetulan lolos, skenario
  // "5 retry + escalate" menutup semua karena jumlah baris genap.
  test("tiap baris retry punya id unik agar accordion tidak saling menutup", () => {
    const logs = [retryLog(1, 5, 1000), retryLog(2, 5, 2000), retryLog(3, 5, 4000)];
    const r = buildExecutionReport({ logs, status: "running" } as any);
    const ids = r.steps.filter((s) => s.status === "retrying").map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test("laporan tanpa healing tetap berperilaku seperti sebelumnya", () => {
    const r = buildExecutionReport({
      logs: [{ node_id: "a1", status: "completed", payload: { summary: "selesai" } }],
      status: "completed",
    } as any);
    expect(r.ok).toBe(true);
    expect(r.okCount).toBe(1);
    expect(r.steps[0].healing).toBeUndefined();
    expect(r.steps[0].detail).toBe("selesai");
  });
});
