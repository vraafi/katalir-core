// Query key factory voor chat (TanStack Query v5).
// Consistent patroon — keys zijn deterministisch en invalidatable.
export const chatKeys = {
  all: ["chat"] as const,
  sessions: (email: string) => [...chatKeys.all, "sessions", email] as const,
  messages: (sessionId: string) => [...chatKeys.all, "messages", sessionId] as const,
};