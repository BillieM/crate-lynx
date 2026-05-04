type EmptyStateTone = "error" | "neutral";

type EmptyStateCardProps = {
  body: string;
  className?: string;
  title: string;
  tone?: EmptyStateTone;
};

const toneClasses = {
  error: "border-ctp-red/30 bg-ctp-surface0/60 text-ctp-red",
  neutral: "border-ctp-surface1/80 bg-ctp-mantle text-ctp-subtext0",
} satisfies Record<EmptyStateTone, string>;

export function EmptyStateCard({ body, className = "", title, tone = "neutral" }: EmptyStateCardProps) {
  return (
    <div className={`rounded-[24px] border px-6 py-6 text-center ${toneClasses[tone]} ${className}`}>
      <h2 className="text-[18px] font-semibold text-ctp-text">{title}</h2>
      <p className="mt-2 text-[13px] leading-6">{body}</p>
    </div>
  );
}
