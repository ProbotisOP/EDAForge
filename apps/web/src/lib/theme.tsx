import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemeMode = "light" | "dark";

export interface ChartThemeTokens {
  isDark: boolean;
  text: string;
  subtext: string;
  axisLabel: string;
  axisLine: string;
  splitLine: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  primary: string;
  primarySoft: string;
  secondary: string;
  positive: string;
  negative: string;
  warning: string;
  neutral: string;
  bandFill: string;
  iqrFill: string;
  palette: string[];
  heatmapRamp: string[];
  divergingRamp: string[];
}

const LIGHT_TOKENS: ChartThemeTokens = {
  isDark: false,
  text: "#12191D",
  subtext: "#46545D",
  axisLabel: "#46545D",
  axisLine: "#CBD6DA",
  splitLine: "#E6EEF0",
  tooltipBg: "#FFFFFF",
  tooltipBorder: "#C5D2D7",
  tooltipText: "#12191D",
  primary: "#1A5F68",
  primarySoft: "rgba(26, 95, 104, 0.15)",
  secondary: "#C84B31",
  positive: "#0F766E",
  negative: "#B91C1C",
  warning: "#A14A08",
  neutral: "#586873",
  bandFill: "rgba(26, 95, 104, 0.11)",
  iqrFill: "rgba(26, 95, 104, 0.16)",
  palette: ["#1A5F68", "#C84B31", "#2B59C3", "#0F766E", "#A14A08", "#6B4E71", "#2A6F97", "#4A5568"],
  heatmapRamp: ["#F4F8F9", "#CBE7EA", "#77BFC7", "#247682", "#163A40"],
  divergingRamp: ["#B91C1C", "#F4A593", "#EEF3F5", "#7CC6D0", "#164E56"],
};

const DARK_TOKENS: ChartThemeTokens = {
  isDark: true,
  text: "#EFF4F6",
  subtext: "#A2B3BC",
  axisLabel: "#A2B3BC",
  axisLine: "#2F3E45",
  splitLine: "#202B30",
  tooltipBg: "#182024",
  tooltipBorder: "#34464E",
  tooltipText: "#EFF4F6",
  primary: "#4CC9F0",
  primarySoft: "rgba(76, 201, 240, 0.20)",
  secondary: "#5EEAD4",
  positive: "#34D399",
  negative: "#FB7185",
  warning: "#FBBF24",
  neutral: "#8B9FA9",
  bandFill: "rgba(76, 201, 240, 0.14)",
  iqrFill: "rgba(76, 201, 240, 0.19)",
  palette: ["#4CC9F0", "#34D399", "#FBBF24", "#FB7185", "#A5B4FC", "#2DD4BF", "#FDBA74", "#CBD5E1"],
  heatmapRamp: ["#171F23", "#1D4249", "#246E7B", "#4CC9F0", "#CAF0F8"],
  divergingRamp: ["#FB7185", "#881337", "#233036", "#1E6073", "#4CC9F0"],
};

interface ThemeContextValue {
  theme: ThemeMode;
  setTheme: (t: ThemeMode) => void;
  toggleTheme: () => void;
  tokens: ChartThemeTokens;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "light",
  setTheme: () => {},
  toggleTheme: () => {},
  tokens: LIGHT_TOKENS,
});

const STORAGE_KEY = "edaforge-theme";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "light" || saved === "dark") return saved;
    } catch {
      /* ignore storage errors */
    }
    return "light";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", theme === "dark" ? "#0D0B0F" : "#DCE8EB");
    }
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      setTheme,
      toggleTheme: () => setTheme((prev) => (prev === "dark" ? "light" : "dark")),
      tokens: theme === "dark" ? DARK_TOKENS : LIGHT_TOKENS,
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

export { DARK_TOKENS, LIGHT_TOKENS };
