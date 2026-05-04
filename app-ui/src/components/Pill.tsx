import type { HTMLAttributes, ReactNode } from "react";
import { controlClasses } from "../styles/componentClasses";
import { pillToneClasses, type PillTone } from "../styles/toneClasses";

type PillProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: PillTone;
};

const baseClasses = `${controlClasses.pill} ring-1 ring-inset`;

export function Pill({ children, className = "", tone = "neutral", ...props }: PillProps) {
  return (
    <span className={`${baseClasses} ${pillToneClasses[tone]} ${className}`} {...props}>
      {children}
    </span>
  );
}
