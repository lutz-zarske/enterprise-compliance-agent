"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

/** Gewaehlte Darstellung; "system" folgt dem Betriebssystem (prefers-color-scheme). */
export type ThemeChoice = "dark" | "light" | "system";
export type Theme = "dark" | "light";

interface ThemeContextValue {
  /** Tatsaechlich angezeigtes Farbschema. */
  theme: Theme;
  /** Gespeicherte Wahl (dark | light | system). */
  choice: ThemeChoice;
  setTheme: (theme: Theme) => void;
  setChoice: (choice: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  choice: "dark",
  setTheme: () => undefined,
  setChoice: () => undefined,
});

export const THEME_STORAGE_KEY = "eca-theme";

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function apply(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.style.colorScheme = theme;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>("dark");
  const [theme, setThemeState] = useState<Theme>("dark");

  // Das Inline-Script im Layout hat die Klasse bereits gesetzt - hier nur uebernehmen.
  useEffect(() => {
    let stored: ThemeChoice = "dark";
    try {
      const raw = localStorage.getItem(THEME_STORAGE_KEY);
      if (raw === "light" || raw === "dark" || raw === "system") stored = raw;
    } catch {
      /* privater Modus */
    }
    setChoiceState(stored);
    setThemeState(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);

  // "system": Wechsel des Betriebssystems live uebernehmen.
  useEffect(() => {
    if (choice !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      const next = systemTheme();
      apply(next);
      setThemeState(next);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [choice]);

  const setChoice = useCallback((next: ThemeChoice) => {
    const resolved = next === "system" ? systemTheme() : next;
    apply(resolved);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* privater Modus: Wahl gilt nur fuer diese Sitzung */
    }
    setChoiceState(next);
    setThemeState(resolved);
  }, []);

  const setTheme = useCallback((next: Theme) => setChoice(next), [setChoice]);

  return <ThemeContext.Provider value={{ theme, choice, setTheme, setChoice }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
