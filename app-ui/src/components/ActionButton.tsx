import type { ButtonHTMLAttributes, ReactNode } from "react";
import { controlClasses } from "../styles/componentClasses";
import { actionButtonToneClasses, type ActionButtonTone } from "../styles/toneClasses";

type ActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  tone?: ActionButtonTone;
};

const baseClasses = controlClasses.actionButton;

export function ActionButton({ children, className = "", tone = "neutral", type = "button", ...props }: ActionButtonProps) {
  return (
    <button className={`${baseClasses} ${actionButtonToneClasses[tone]} ${className}`} type={type} {...props}>
      {children}
    </button>
  );
}
