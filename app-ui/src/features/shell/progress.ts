export type ProgressStatus = "unlinked" | "pending" | "linked";

export type ProgressColor = string;

const progressPalette = {
  linked: "var(--color-ctp-green)",
  pending: "var(--color-ctp-yellow)",
  unlinked: "var(--color-ctp-overlay0)",
} satisfies Record<ProgressStatus, ProgressColor>;

function clampPercentage(matchPercentage: number) {
  return Math.max(0, Math.min(100, matchPercentage));
}

function asMixPercentage(amount: number) {
  return `${Math.round((1 - amount) * 10000) / 100}%`;
}

function mixProgressColors(start: ProgressColor, end: ProgressColor, amount: number) {
  if (amount <= 0) {
    return start;
  }

  if (amount >= 1) {
    return end;
  }

  return `color-mix(in srgb, ${start} ${asMixPercentage(amount)}, ${end})`;
}

export function getProgressColor(matchPercentage: number): ProgressColor {
  const normalized = clampPercentage(matchPercentage) / 100;

  if (normalized <= 0.5) {
    return mixProgressColors(progressPalette.unlinked, progressPalette.pending, normalized / 0.5);
  }

  return mixProgressColors(progressPalette.pending, progressPalette.linked, (normalized - 0.5) / 0.5);
}
