import { useId, useRef, type HTMLAttributes, type KeyboardEvent, type ReactNode } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Gauge, gaugeClasses } from "@mui/x-charts/Gauge";
import { motion, useReducedMotion } from "motion/react";
import { playDetent, playTick } from "../lib/sound";
import { useStudioExtras } from "./EasterEggs";

export const KBD_SHORTCUT =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.platform) ? "⌘K" : "Ctrl K";

/**
 * Architectural Dual-World Bento mark for EDAForge.
 * Clicking 5 times rapidly unlocks Anscombe's Secret Lab!
 */
export function BrandMark({ size = 30 }: { size?: number }) {
  const { registerBrandClick } = useStudioExtras();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className="brand-mark-svg"
      aria-hidden="true"
      onClick={() => registerBrandClick()}
    >
      <rect width="32" height="32" rx="9" fill="var(--brand-mark-bg)" />
      <rect x="6.5" y="16" width="4" height="9.5" rx="2" fill="#5EEAD4" />
      <rect x="14" y="10.5" width="4" height="15" rx="2" fill="#F3F9FA" />
      <rect x="21.5" y="6.5" width="4" height="19" rx="2" fill="#4CC9F0" />
    </svg>
  );
}

export type BentoTone = "surface" | "petrol" | "sage" | "coral" | "sand" | "sky" | "alabaster";

export function BentoTile({
  tone = "surface",
  className = "",
  children,
  onClick,
  ...rest
}: HTMLAttributes<HTMLDivElement> & {
  tone?: BentoTone;
  children: ReactNode;
}) {
  return (
    <div
      className={`bento-tile bento-${tone}${onClick ? " bento-hit is-clickable" : ""} ${className}`.trim()}
      onClick={(e) => {
        if (onClick) {
          playTick(0.95);
          onClick(e);
        }
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

export function SpotlightCard({
  children,
  className = "",
  beam: _beam = false,
  onClick,
  ...rest
}: HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  className?: string;
  beam?: boolean;
}) {
  return (
    <div
      className={`card${onClick ? " bento-hit is-clickable" : ""} ${className}`.trim()}
      onClick={(e) => {
        if (onClick) {
          playTick(0.95);
          onClick(e);
        }
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

export function NumberTicker({
  value,
  decimals = 0,
  suffix = "",
  prefix = "",
  className = "",
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  prefix?: string;
  className?: string;
}) {
  const formatted =
    decimals > 0
      ? value.toLocaleString(undefined, {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        })
      : Math.round(value).toLocaleString();

  return (
    <span className={`tabular-nums ${className}`.trim()}>
      {prefix}
      {formatted}
      {suffix}
    </span>
  );
}

/**
 * Tactile pill segmented control with shared spring pill and roving keyboard focus.
 */
export function SpringSegmented<T extends string>({
  value,
  onChange,
  items,
  ariaLabel,
  role = "tablist",
  size = "md",
}: {
  value: T;
  onChange: (v: T) => void;
  items: { id: T; label: ReactNode; title?: string; disabled?: boolean }[];
  ariaLabel?: string;
  role?: "tablist" | "radiogroup" | "group";
  size?: "xs" | "md";
}) {
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const groupId = useId();
  const reduce = useReducedMotion();
  const itemRole = role === "tablist" ? "tab" : role === "radiogroup" ? "radio" : undefined;

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (role === "group") return;
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const enabledIndices = items.map((it, i) => (it.disabled ? -1 : i)).filter((i) => i >= 0);
    if (!enabledIndices.length) return;
    const curPos = enabledIndices.indexOf(items.findIndex((it) => it.id === value));
    const delta = e.key === "ArrowRight" ? 1 : -1;
    const nextIdx = enabledIndices[(curPos + delta + enabledIndices.length) % enabledIndices.length];
    const nextItem = items[nextIdx];
    if (nextItem) {
      e.preventDefault();
      playDetent();
      onChange(nextItem.id);
      btnRefs.current[nextIdx]?.focus();
    }
  };

  return (
    <div
      className={`seg${size === "xs" ? " seg-xs" : ""}`}
      role={role}
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
    >
      {items.map((item, idx) => {
        const active = value === item.id;
        return (
          <button
            key={item.id}
            ref={(el) => {
              btnRefs.current[idx] = el;
            }}
            type="button"
            role={itemRole}
            aria-selected={itemRole === "tab" ? active : undefined}
            aria-checked={itemRole === "radio" ? active : undefined}
            disabled={item.disabled}
            title={item.title}
            className={active ? "active" : ""}
            onClick={() => {
              if (!active) playDetent();
              onChange(item.id);
            }}
          >
            {active ? (
              <motion.span
                layoutId={`seg-pill-${groupId}`}
                className="seg-active-bg"
                transition={
                  reduce
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 440, damping: 34, mass: 0.6 }
                }
              />
            ) : null}
            <span className="seg-label-inner">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * MUI X Charts v9 Radial Gauge for Data Health scoring.
 */
export function HealthGauge({
  score,
  color,
}: {
  score: number;
  color: string;
}) {
  const clamped = Math.max(0, Math.min(100, score));

  return (
    <div className="health-gauge" aria-label="health score">
      <Gauge
        width={68}
        height={68}
        value={clamped}
        valueMin={0}
        valueMax={100}
        startAngle={-125}
        endAngle={125}
        innerRadius="72%"
        outerRadius="100%"
        cornerRadius="50%"
        margin={0}
        text={() => (Number.isInteger(score) ? `${score}` : score.toFixed(1))}
        sx={{
          [`& .${gaugeClasses.valueArc}`]: {
            fill: color,
          },
          [`& .${gaugeClasses.referenceArc}`]: {
            fill: "currentColor",
            fillOpacity: 0.16,
          },
          [`& .${gaugeClasses.valueText}`]: {
            fontSize: 13.5,
            fontWeight: 750,
            fontFamily: "var(--mono)",
            "& text": {
              fill: color,
            },
          },
        }}
      />
    </div>
  );
}

export function Tip({
  content,
  children,
}: {
  content: ReactNode;
  children: ReactNode;
}) {
  return (
    <TooltipPrimitive.Provider delayDuration={180}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content className="radix-tooltip" sideOffset={7}>
            {content}
            <TooltipPrimitive.Arrow className="radix-tooltip-arrow" />
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
