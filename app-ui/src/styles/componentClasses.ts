const borderClasses = {
  default: "border border-ctp-surface1/80",
  muted: "border border-ctp-surface0",
};

const radiusClasses = {
  card: "rounded-[8px]",
  control: "rounded-[8px]",
  panel: "rounded-[8px]",
  popover: "rounded-[10px]",
  artwork: "rounded-[12px]",
  pill: "rounded-full",
};

const shadowClasses = {
  compact: "shadow-sm shadow-ctp-crust/20",
  elevated: "shadow-[0_12px_32px_color-mix(in_srgb,var(--color-ctp-crust)_18%,transparent)]",
  popover: "shadow-[0_14px_34px_color-mix(in_srgb,var(--color-ctp-crust)_34%,transparent)]",
};

const surfaceFillClasses = {
  card: "bg-ctp-mantle/80",
  elevated:
    "bg-[linear-gradient(135deg,color-mix(in_srgb,var(--color-ctp-base)_96%,transparent),color-mix(in_srgb,var(--color-ctp-surface0)_92%,transparent))]",
  inset: "bg-ctp-surface0/72",
  row: "bg-[linear-gradient(180deg,color-mix(in_srgb,var(--color-ctp-surface0)_92%,transparent),color-mix(in_srgb,var(--color-ctp-base)_96%,transparent))]",
};

export const surfaceClasses = {
  cardRadius: radiusClasses.card,
  compactCard: `${radiusClasses.card} ${borderClasses.muted} ${surfaceFillClasses.card} p-4 ${shadowClasses.compact}`,
  dashedPlaceholder: `${radiusClasses.card} border border-dashed border-ctp-surface0 px-4 py-3`,
  emptyState: `${radiusClasses.card} border px-4 py-4 text-center`,
  elevatedPanel:
    `${radiusClasses.panel} ${borderClasses.default} ${surfaceFillClasses.elevated} px-5 py-5 ${shadowClasses.elevated}`,
  insetPanel: `${radiusClasses.panel} ${surfaceFillClasses.inset} ring-1 ring-inset ring-ctp-surface1/80`,
  panelRadius: radiusClasses.panel,
  popover: `${radiusClasses.popover} border border-ctp-surface1 bg-ctp-mantle ${shadowClasses.popover}`,
  popoverBody: "px-3 py-2.5",
  raisedArtwork: `${radiusClasses.artwork} ${shadowClasses.elevated} ring-1 ring-inset ring-ctp-surface1/80`,
  statusPanel: `${radiusClasses.panel} border px-3.5 py-2.5`,
  trackCard: `${radiusClasses.card} ${borderClasses.default} ${surfaceFillClasses.row} ${shadowClasses.compact}`,
  rowCard: `grid gap-3 px-4 py-3 ${radiusClasses.card} ${borderClasses.default} ${surfaceFillClasses.row} ${shadowClasses.compact}`,
  rowCardCompact: `grid gap-2.5 px-3.5 py-2.5 ${radiusClasses.card} ${borderClasses.default} ${surfaceFillClasses.row} ${shadowClasses.compact}`,
};

export const textClasses = {
  bodyMuted: "text-[13px] text-ctp-subtext0",
  bodyRelaxed: "text-[12px] leading-5",
  bodyMutedRelaxed: "text-[12px] leading-5 text-ctp-subtext0",
  caption: "text-[12px] text-ctp-subtext0",
  detail: "text-[12px] font-medium text-ctp-overlay1",
  eyebrow: "text-[11px] font-semibold uppercase tracking-[0.16em]",
  finePrint: "text-[11px]",
  input: "text-[13px]",
  label: "text-[13px] font-semibold text-ctp-text",
  metric: "text-[12px] font-semibold tabular-nums text-ctp-text",
  microEyebrow: "text-[10px] font-semibold uppercase tracking-[0.16em]",
  navItem: "text-[13px] font-medium",
  pillEyebrow: "text-[11px] font-semibold uppercase tracking-[0.14em]",
  playlistTitle: "text-[22px] font-semibold text-ctp-text sm:text-[24px]",
  proposalTitle: "text-[14px] font-semibold text-ctp-text",
  score: "text-[15px] font-semibold text-ctp-text",
  sectionTitle: "text-[18px] font-semibold text-ctp-text",
  status: "text-[12px] font-medium",
  title: "text-[15px] font-semibold text-ctp-text",
};

export const controlClasses = {
  actionButton:
    `${radiusClasses.control} border px-3 py-1.5 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:bg-ctp-surface0 disabled:text-ctp-overlay1 disabled:hover:bg-ctp-surface0`,
  actionButtonCompact: "px-2.5 py-1 text-[11px]",
  controlRadius: radiusClasses.control,
  countBadge:
    `${radiusClasses.pill} min-w-6 bg-ctp-mantle px-2 py-0.5 text-center text-[11px] font-semibold tabular-nums text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1`,
  countBadgeCompact:
    `${radiusClasses.pill} min-w-5 bg-ctp-mantle px-1.5 py-0 text-center text-[10px] font-semibold tabular-nums text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1`,
  filterChip:
    `${radiusClasses.pill} inline-flex min-h-8 items-center gap-2 border px-3 text-[12px] font-semibold transition-colors`,
  filterChipCompact:
    `${radiusClasses.pill} inline-flex min-h-7 items-center gap-1.5 border px-2.5 text-[11px] font-semibold transition-colors`,
  filterChipGroup: "flex flex-wrap items-center gap-2",
  filterChipGroupCompact: "flex flex-wrap items-center gap-1.5",
  filterChipInactive:
    "border-ctp-surface1 bg-ctp-surface0 text-ctp-subtext0 hover:border-ctp-overlay0 hover:bg-ctp-surface1 hover:text-ctp-text",
  iconFrame: `flex items-center justify-center ${radiusClasses.control} bg-ctp-surface0 text-ctp-mauve`,
  iconButton:
    `${radiusClasses.control} inline-flex h-7 w-7 shrink-0 items-center justify-center border border-ctp-surface1 bg-ctp-surface0 p-0 text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1 focus:outline-none focus-visible:ring-2 focus-visible:ring-ctp-mauve/45 disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:bg-ctp-surface0 disabled:text-ctp-overlay1 disabled:hover:bg-ctp-surface0 [&_svg]:block [&_svg]:h-4 [&_svg]:w-4`,
  iconButtonTooltip:
    "pointer-events-none absolute right-0 top-[calc(100%+0.45rem)] z-20 whitespace-nowrap rounded-[6px] border border-ctp-surface1 bg-ctp-crust px-2 py-1 text-[11px] font-medium text-ctp-text opacity-0 shadow-sm shadow-ctp-crust/30 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100",
  pill: `${radiusClasses.pill} px-2 py-0.5 text-[11px] font-semibold`,
  popoverOffset: "top-[calc(100%+0.5rem)]",
  searchFrame:
    `${radiusClasses.control} bg-ctp-surface0 ring-1 ring-inset ring-ctp-surface1/70 focus-within:text-ctp-text focus-within:ring-ctp-overlay0`,
};

export const shellClasses = {
  brandEyebrow: "font-display text-[10px] font-bold uppercase tracking-[0.26em]",
  navBadge: "px-1.5 py-0 text-[10px]",
  navItem:
    `flex w-full items-center gap-2.5 px-3.5 py-2 text-left transition-colors hover:bg-ctp-surface0/80 ${radiusClasses.control}`,
  navSection: "space-y-2",
  navSectionTitle: "px-3.5 tracking-[0.18em]",
  navStack: "space-y-1",
  sidebar:
    "flex min-h-0 w-[208px] shrink-0 flex-col border-r border-ctp-surface0 bg-ctp-mantle max-md:max-h-[45vh] max-md:w-full max-md:border-b",
  sidebarBody: "flex-1 space-y-4 overflow-y-auto px-0 py-4",
  sidebarHeader: "border-b border-ctp-surface0 px-4 py-3.5",
  sidebarLogo: `flex h-8 w-8 items-center justify-center ${radiusClasses.control} bg-ctp-surface0 text-ctp-mauve`,
  topbar:
    "flex h-10 min-h-10 shrink-0 items-center justify-between border-b border-ctp-surface0 bg-ctp-mantle px-4 max-md:h-auto max-md:flex-wrap max-md:gap-2 max-md:py-2",
  topbarIcon: "h-7 w-7",
};

export const layoutClasses = {
  artworkCompact: "h-16 w-16 sm:h-[72px] sm:w-[72px]",
  coverageMeter: "min-w-[11rem] sm:min-w-[13rem]",
  emptyStateNarrow: "max-w-[420px]",
  progressDigit: "min-w-[2ch]",
};
