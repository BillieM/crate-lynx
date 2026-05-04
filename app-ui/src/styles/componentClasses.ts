export const surfaceClasses = {
  cardRadius: "rounded-[24px]",
  compactCard: "rounded-[8px] border border-ctp-surface0 bg-ctp-mantle/80 p-4 shadow-sm shadow-ctp-crust/20",
  elevatedPanel:
    "rounded-[30px] border border-ctp-surface1/80 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--color-ctp-base)_96%,transparent),color-mix(in_srgb,var(--color-ctp-surface0)_92%,transparent))] px-6 py-6 shadow-[0_24px_64px_color-mix(in_srgb,var(--color-ctp-crust)_24%,transparent)]",
  insetPanel: "rounded-[18px] bg-ctp-surface0/72 ring-1 ring-inset ring-ctp-surface1/80",
  panelRadius: "rounded-[18px]",
  popover:
    "rounded-[12px] border border-ctp-surface1 bg-ctp-mantle shadow-[0_20px_48px_color-mix(in_srgb,var(--color-ctp-crust)_38%,transparent)]",
  raisedArtwork:
    "rounded-[24px] shadow-[0_18px_42px_color-mix(in_srgb,var(--color-ctp-crust)_28%,transparent)] ring-1 ring-inset ring-ctp-surface1/80",
  trackCard:
    "rounded-[24px] border border-ctp-surface1/80 bg-[linear-gradient(180deg,color-mix(in_srgb,var(--color-ctp-surface0)_92%,transparent),color-mix(in_srgb,var(--color-ctp-base)_96%,transparent))] shadow-[0_16px_36px_color-mix(in_srgb,var(--color-ctp-crust)_18%,transparent)]",
};

export const textClasses = {
  bodyMuted: "text-[13px] text-ctp-subtext0",
  bodyRelaxed: "text-[12px] leading-5",
  bodyMutedRelaxed: "text-[12px] leading-5 text-ctp-subtext0",
  caption: "text-[12px] text-ctp-subtext0",
  detail: "text-[12px] font-medium text-ctp-overlay1",
  eyebrow: "text-[11px] font-semibold uppercase tracking-[0.16em]",
  sectionTitle: "text-[18px] font-semibold text-ctp-text",
  title: "text-[15px] font-semibold text-ctp-text",
};

export const controlClasses = {
  controlRadius: "rounded-[10px]",
  iconFrame: "flex items-center justify-center rounded-[10px] bg-ctp-surface0 text-ctp-mauve",
  pill: "rounded-full px-2.5 py-1 text-[11px] font-semibold",
  searchFrame:
    "rounded-[10px] bg-ctp-surface0 ring-1 ring-inset ring-ctp-surface1/70 focus-within:text-ctp-text focus-within:ring-ctp-overlay0",
};
