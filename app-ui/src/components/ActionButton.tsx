import type { ButtonHTMLAttributes, ReactNode } from "react";
import { actionButtonToneClasses, type ActionButtonTone } from "../styles/toneClasses";

type ActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  tone?: ActionButtonTone;
};

const baseClasses =
  "rounded-[10px] border px-3 py-1.5 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:bg-ctp-surface0 disabled:text-ctp-overlay1";

export function ActionButton({ children, className = "", tone = "neutral", type = "button", ...props }: ActionButtonProps) {
  return (
    <button className={`${baseClasses} ${actionButtonToneClasses[tone]} ${className}`} type={type} {...props}>
      {children}
    </button>
  );
}
