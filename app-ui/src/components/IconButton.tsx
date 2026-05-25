import { type ButtonHTMLAttributes, type ReactNode, useId } from "react";
import { controlClasses } from "../styles/componentClasses";

type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "children" | "title"> & {
  children: ReactNode;
  label: string;
  tooltip?: string;
  wrapperClassName?: string;
};

export function IconButton({
  children,
  className = "",
  label,
  tooltip = label,
  type = "button",
  wrapperClassName = "",
  ...props
}: IconButtonProps) {
  const tooltipId = useId();

  return (
    <span className={`group relative inline-flex ${wrapperClassName}`}>
      <button
        aria-describedby={tooltipId}
        aria-label={label}
        className={`${controlClasses.iconButton} ${className}`}
        title={tooltip}
        type={type}
        {...props}
      >
        {children}
      </button>
      <span className={controlClasses.iconButtonTooltip} id={tooltipId} role="tooltip">
        {tooltip}
      </span>
    </span>
  );
}
