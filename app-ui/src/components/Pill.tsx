import type { HTMLAttributes, ReactNode } from "react";

type PillTone = "accent" | "danger" | "info" | "neutral" | "pending" | "success";

type PillProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: PillTone;
};

const baseClasses = "rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset";

const toneClasses = {
  accent: "bg-ctp-mauve/20 text-ctp-mauve ring-ctp-mauve/30",
  danger: "bg-ctp-red/18 text-ctp-red ring-ctp-red/30",
  info: "bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30",
  neutral: "bg-ctp-surface0 text-ctp-subtext0 ring-ctp-surface1/70",
  pending: "bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30",
  success: "bg-ctp-green/18 text-ctp-green ring-ctp-green/30",
} satisfies Record<PillTone, string>;

export function Pill({ children, className = "", tone = "neutral", ...props }: PillProps) {
  return (
    <span className={`${baseClasses} ${toneClasses[tone]} ${className}`} {...props}>
      {children}
    </span>
  );
}
