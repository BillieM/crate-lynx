export type OperationStatus = "error" | "pending" | "success";

type StatusMessageProps = {
  body: string;
  status: OperationStatus;
  title: string;
};

const statusClasses = {
  error: "border-ctp-red/30 bg-ctp-red/10 text-ctp-red",
  pending: "border-ctp-yellow/30 bg-ctp-yellow/10 text-ctp-yellow",
  success: "border-ctp-green/30 bg-ctp-green/10 text-ctp-green",
} satisfies Record<OperationStatus, string>;

export function StatusMessage({ body, status, title }: StatusMessageProps) {
  return (
    <section className={`rounded-[18px] border px-5 py-4 ${statusClasses[status]}`}>
      <h3 className="text-[13px] font-semibold text-ctp-text">{title}</h3>
      <p className="mt-1 text-[12px] leading-5">{body}</p>
    </section>
  );
}
