import { id } from "./id";
import { en } from "./en";

export type Locale = "id" | "en";
export const LOCALES: Locale[] = ["id", "en"];
export const DEFAULT_LOCALE: Locale = "id";
export const STORAGE_KEY = "katalir.locale.v1";

export const messages = { id, en } as const;
export type Messages = typeof id;
