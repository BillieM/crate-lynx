import type { ButtonHTMLAttributes, ReactNode } from "react";

type ActionButtonTone = "danger" | "neutral" | "success";

type ActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  tone?: ActionButtonTone;
};

const baseClasses =
  "rounded-[10px] border px-3 py-1.5 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:bg-ctp-surface0 disabled:text-ctp-overlay1";

const toneClasses = {
  danger: "border-ctp-red/40 bg-ctp-red/12 text-ctp-red hover:bg-ctp-red/18",
  neutral: "border-ctp-surface1 bg-ctp-surface0 text-ctp-text hover:border-ctp-overlay0 hover:bg-ctp-surface1",
  success: "border-ctp-green/40 bg-ctp-green/12 text-ctp-green hover:bg-ctp-green/18",
} satisfies Record<ActionButtonTone, string>;

export function ActionButton({ children, className = "", tone = "neutral", type = "button", ...props }: ActionButtonProps) {
  return (
    <button className={`${baseClasses} ${toneClasses[tone]} ${className}`} type={type} {...props}>
      {children}
    </button>
  );
}
