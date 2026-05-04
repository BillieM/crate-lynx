import { statusMessageClasses, type OperationStatus } from "../styles/toneClasses";

export type { OperationStatus };

type StatusMessageProps = {
  body: string;
  status: OperationStatus;
  title: string;
};

export function StatusMessage({ body, status, title }: StatusMessageProps) {
  return (
    <section className={`rounded-[18px] border px-5 py-4 ${statusMessageClasses[status]}`}>
      <h3 className="text-[13px] font-semibold text-ctp-text">{title}</h3>
      <p className="mt-1 text-[12px] leading-5">{body}</p>
    </section>
  );
}
