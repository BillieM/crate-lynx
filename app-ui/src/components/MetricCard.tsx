import type { LucideIcon } from "lucide-react";

import { surfaceClasses, textClasses } from "../styles/componentClasses";

type MetricCardProps = {
  className?: string;
  icon: LucideIcon;
  label: string;
  toneClass: string;
  value: number | string;
};

export function MetricCard({
  className = "",
  icon: Icon,
  label,
  toneClass,
  value,
}: MetricCardProps) {
  return (
    <section className={`${surfaceClasses.compactCard} min-h-24 ${className}`} aria-label={label}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`${textClasses.microEyebrow} text-ctp-subtext0`}>{label}</p>
          <p className="mt-2 text-[24px] font-semibold leading-none tabular-nums text-ctp-text">{value}</p>
        </div>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] ring-1 ring-inset ${toneClass}`}>
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.8} />
        </div>
      </div>
    </section>
  );
}
