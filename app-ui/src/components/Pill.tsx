import type { HTMLAttributes, ReactNode } from "react";
import { pillToneClasses, type PillTone } from "../styles/toneClasses";

type PillProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: PillTone;
};

const baseClasses = "rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset";

export function Pill({ children, className = "", tone = "neutral", ...props }: PillProps) {
  return (
    <span className={`${baseClasses} ${pillToneClasses[tone]} ${className}`} {...props}>
      {children}
    </span>
  );
}
