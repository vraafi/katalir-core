// Query key factory voor chat (TanStack Query v5).
// Consistent patroon — keys zijn deterministisch en invalidatable.
export const chatKeys = {
  all: ["chat"] as const,
  sessions: (email: string) => [...chatKeys.all, "sessions", email] as const,
  messages: (sessionId: string) => [...chatKeys.all, "messages", sessionId] as const,
};

// Query keys untuk Template Gallery (Fitur #10). Daftar difilter server-side
// lewat query param, jadi kategori + pencarian masuk ke dalam key agar cache
// tidak menyajikan hasil filter yang salah.
export const templateKeys = {
  all: ["templates"] as const,
  list: (category: string, q: string) =>
    [...templateKeys.all, "list", category, q] as const,
  info: () => [...templateKeys.all, "info"] as const,
};

// Query keys untuk Agents (TASK 5 / Fitur #1). Agent adalah entitas kelas satu
// dengan siklus hidup; filter status dikirim ke server, jadi status masuk ke
// dalam key agar cache tidak menyajikan daftar terfilter yang salah.
export const agentKeys = {
  all: ["agents"] as const,
  list: (status: string) => [...agentKeys.all, "list", status] as const,
  detail: (id: string) => [...agentKeys.all, "detail", id] as const,
  mcp: (id: string) => [...agentKeys.all, "mcp", id] as const,
};