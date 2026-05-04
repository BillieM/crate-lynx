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
      <h3 className={textClasses.label}>{title}</h3>
      <p className={`mt-1 ${textClasses.bodyRelaxed}`}>{body}</p>
    </section>
  );
}
