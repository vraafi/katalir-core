"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

export const THEME_KEY = "katalir.theme";
export function applyAppTheme(theme: "light" | "dark") {
  document.documentElement.classList.remove("light");
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.style.colorScheme = theme;
  window.localStorage.setItem(THEME_KEY, theme);
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const saved = window.localStorage.getItem(THEME_KEY);
    const initial = saved === "dark" || saved === "light"
      ? saved
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    setTheme(initial);
    applyAppTheme(initial);
    setReady(true);
  }, []);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyAppTheme(next);
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Ganti tema gelap/terang"
      data-testid="theme-toggle"
      data-theme-ready={ready ? "true" : "false"}
      onClick={toggle}
    >
      {theme === "dark" ? <Sun className="h-4 w-4" strokeWidth={1.75} aria-hidden /> : <Moon className="h-4 w-4" strokeWidth={1.75} aria-hidden />}
    </Button>
  );
}
