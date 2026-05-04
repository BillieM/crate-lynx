import { surfaceClasses, textClasses } from "../styles/componentClasses";
import { statusMessageClasses, type OperationStatus } from "../styles/toneClasses";

export type { OperationStatus };

type StatusMessageProps = {
  body: string;
  className?: string;
  status: OperationStatus;
  title: string;
};

export function StatusMessage({ body, className = "", status, title }: StatusMessageProps) {
  return (
    <section className={`${surfaceClasses.statusPanel} ${statusMessageClasses[status]} ${className}`}>
      <h3 className="text-[13px] font-semibold text-ctp-text">{title}</h3>
      <p className={`mt-1 ${textClasses.bodyRelaxed}`}>{body}</p>
    </section>
  );
}
