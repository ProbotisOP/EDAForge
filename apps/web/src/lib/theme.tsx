import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { createTheme, ThemeProvider as MuiThemeProvider, type Theme } from "@mui/material/styles";

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
  axisLabel: "#4A5A64",
  axisLine: "#CFDCE0",
  splitLine: "#E3ECEF",
  tooltipBg: "#FFFFFF",
  tooltipBorder: "#C5D4DA",
  tooltipText: "#12191D",
  primary: "#156570",
  primarySoft: "rgba(21, 101, 112, 0.20)",
  secondary: "#E05A47",
  positive: "#0D8A72",
  negative: "#C8372D",
  warning: "#D97706",
  neutral: "#5B707B",
  bandFill: "rgba(224, 90, 71, 0.16)",
  iqrFill: "rgba(21, 101, 112, 0.18)",
  palette: [
    "#156570",
    "#E05A47",
    "#0D8A72",
    "#2563EB",
    "#D97706",
    "#0891B2",
    "#4F46E5",
    "#475569",
  ],
  heatmapRamp: ["#EEF5F7", "#BCE3E8", "#5BB5C0", "#176B77", "#113B42"],
  divergingRamp: ["#C8372D", "#F29F8F", "#EDF3F5", "#6BC0CC", "#155861"],
};

const DARK_TOKENS: ChartThemeTokens = {
  isDark: true,
  text: "#EFF4F6",
  subtext: "#A4B6BF",
  axisLabel: "#9FB2BC",
  axisLine: "#2B3A42",
  splitLine: "#1F2B31",
  tooltipBg: "#182126",
  tooltipBorder: "#364A54",
  tooltipText: "#EFF4F6",
  primary: "#38BDF8",
  primarySoft: "rgba(56, 189, 248, 0.24)",
  secondary: "#FB7185",
  positive: "#34D399",
  negative: "#FB7185",
  warning: "#FBBF24",
  neutral: "#7E95A2",
  bandFill: "rgba(251, 113, 133, 0.18)",
  iqrFill: "rgba(56, 189, 248, 0.22)",
  palette: [
    "#38BDF8",
    "#FB7185",
    "#34D399",
    "#FBBF24",
    "#2DD4BF",
    "#818CF8",
    "#FDBA74",
    "#93C5FD",
  ],
  heatmapRamp: ["#162025", "#1A424B", "#1F7485", "#38BDF8", "#CCF2FE"],
  divergingRamp: ["#FB7185", "#881D3D", "#202C33", "#1A6074", "#38BDF8"],
};

export function createBentoMuiTheme(tokens: ChartThemeTokens): Theme {
  return createTheme({
    palette: {
      mode: tokens.isDark ? "dark" : "light",
      primary: { main: tokens.primary },
      secondary: { main: tokens.secondary },
      success: { main: tokens.positive },
      warning: { main: tokens.warning },
      error: { main: tokens.negative },
      background: {
        default: tokens.isDark ? "#12171A" : "#F6F9FA",
        paper: tokens.tooltipBg,
      },
      text: {
        primary: tokens.text,
        secondary: tokens.subtext,
      },
      divider: tokens.splitLine,
    },
    shape: {
      borderRadius: 12,
    },
    typography: {
      fontFamily: '"Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: 13,
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
            backgroundColor: tokens.tooltipBg,
            border: `1px solid ${tokens.tooltipBorder}`,
            borderRadius: 12,
          },
        },
      },
    },
  });
}

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

  const tokens = theme === "dark" ? DARK_TOKENS : LIGHT_TOKENS;
  const muiTheme = useMemo(() => createBentoMuiTheme(tokens), [tokens]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      setTheme,
      toggleTheme: () => setTheme((prev) => (prev === "dark" ? "light" : "dark")),
      tokens,
    }),
    [theme, tokens],
  );

  return (
    <ThemeContext.Provider value={value}>
      <MuiThemeProvider theme={muiTheme}>{children}</MuiThemeProvider>
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

export { DARK_TOKENS, LIGHT_TOKENS };
