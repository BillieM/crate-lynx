export type ActionButtonTone = "danger" | "neutral" | "success";
export type EmptyStateTone = "error" | "neutral";
export type OperationStatus = "error" | "pending" | "success";
export type PillTone = "accent" | "danger" | "info" | "neutral" | "pending" | "success";
export type TrackStatusTone = "linked" | "pending" | "unlinked";
export type FilterChipTone = "all" | TrackStatusTone;

export const actionButtonToneClasses = {
  danger: "border-ctp-red/40 bg-ctp-red/12 text-ctp-red hover:bg-ctp-red/18",
  neutral: "border-ctp-surface1 bg-ctp-surface0 text-ctp-text hover:border-ctp-overlay0 hover:bg-ctp-surface1",
  success: "border-ctp-green/40 bg-ctp-green/12 text-ctp-green hover:bg-ctp-green/18",
} satisfies Record<ActionButtonTone, string>;

export const emptyStateToneClasses = {
  error: "border-ctp-red/30 bg-ctp-surface0/60 text-ctp-red",
  neutral: "border-ctp-surface1/80 bg-ctp-mantle text-ctp-subtext0",
} satisfies Record<EmptyStateTone, string>;

export const pillToneClasses = {
  accent: "bg-ctp-mauve/20 text-ctp-mauve ring-ctp-mauve/30",
  danger: "bg-ctp-red/18 text-ctp-red ring-ctp-red/30",
  info: "bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30",
  neutral: "bg-ctp-surface0 text-ctp-subtext0 ring-ctp-surface1/70",
  pending: "bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30",
  success: "bg-ctp-green/18 text-ctp-green ring-ctp-green/30",
} satisfies Record<PillTone, string>;

export const statusMessageClasses = {
  error: "border-ctp-red/30 bg-ctp-red/10 text-ctp-red",
  pending: "border-ctp-yellow/30 bg-ctp-yellow/10 text-ctp-yellow",
  success: "border-ctp-green/30 bg-ctp-green/10 text-ctp-green",
} satisfies Record<OperationStatus, string>;

export const selectedFilterChipClasses = {
  all: "border-ctp-blue bg-ctp-blue/18 text-ctp-blue shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-blue)_12%,transparent)]",
  linked:
    "border-ctp-green bg-ctp-green/18 text-ctp-green shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-green)_12%,transparent)]",
  pending:
    "border-ctp-yellow bg-ctp-yellow/18 text-ctp-yellow shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-yellow)_12%,transparent)]",
  unlinked:
    "border-ctp-red bg-ctp-red/18 text-ctp-red shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-red)_12%,transparent)]",
} satisfies Record<FilterChipTone, string>;

export const trackStatusDotClasses = {
  linked: "bg-ctp-green shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-green)_14%,transparent)]",
  pending: "bg-ctp-yellow shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-yellow)_16%,transparent)]",
  unlinked: "bg-ctp-red shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-red)_16%,transparent)]",
} satisfies Record<TrackStatusTone, string>;
