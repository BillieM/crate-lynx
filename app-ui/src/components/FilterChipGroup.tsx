import { controlClasses } from "../styles/componentClasses";
import { selectedFilterChipClasses, type FilterChipTone } from "../styles/toneClasses";

export type FilterChipOption<TValue extends string> = {
  count?: number;
  label: string;
  tone: FilterChipTone;
  value: TValue;
};

type FilterChipGroupProps<TValue extends string> = {
  activeValue: TValue;
  ariaLabel: string;
  density?: "default" | "compact";
  onValueChange: (value: TValue) => void;
  options: FilterChipOption<TValue>[];
};

export function FilterChipGroup<TValue extends string>({
  activeValue,
  ariaLabel,
  density = "default",
  onValueChange,
  options,
}: FilterChipGroupProps<TValue>) {
  const chipClasses = density === "compact" ? controlClasses.filterChipCompact : controlClasses.filterChip;
  const countBadgeClasses = density === "compact" ? controlClasses.countBadgeCompact : controlClasses.countBadge;
  const groupClasses = density === "compact" ? controlClasses.filterChipGroupCompact : controlClasses.filterChipGroup;

  return (
    <div aria-label={ariaLabel} className={groupClasses} role="group">
      {options.map((option) => {
        const isSelected = activeValue === option.value;

        return (
          <button
            aria-pressed={isSelected}
            className={`${chipClasses} ${isSelected ? selectedFilterChipClasses[option.tone] : controlClasses.filterChipInactive}`}
            key={option.value}
            onClick={() => onValueChange(option.value)}
            type="button"
          >
            <span>{option.label}</span>
            {option.count !== undefined ? (
              <span className={countBadgeClasses}>{option.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
