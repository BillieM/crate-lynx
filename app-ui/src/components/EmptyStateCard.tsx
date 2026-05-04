import { surfaceClasses, textClasses } from "../styles/componentClasses";
import { emptyStateToneClasses, type EmptyStateTone } from "../styles/toneClasses";

type EmptyStateCardProps = {
  body: string;
  className?: string;
  role?: "alert" | "status";
  title: string;
  tone?: EmptyStateTone;
};

export function EmptyStateCard({ body, className = "", role, title, tone = "neutral" }: EmptyStateCardProps) {
  return (
    <div
      aria-live={role === "alert" ? "assertive" : role === "status" ? "polite" : undefined}
      className={`${surfaceClasses.emptyState} ${emptyStateToneClasses[tone]} ${className}`}
      role={role}
    >
      <h2 className={textClasses.sectionTitle}>{title}</h2>
      <p className="mt-2 text-[13px] leading-6">{body}</p>
    </div>
  );
}
