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
  onValueChange: (value: TValue) => void;
  options: FilterChipOption<TValue>[];
};

export function FilterChipGroup<TValue extends string>({
  activeValue,
  ariaLabel,
  onValueChange,
  options,
}: FilterChipGroupProps<TValue>) {
  return (
    <div aria-label={ariaLabel} className="flex flex-wrap items-center gap-2" role="group">
      {options.map((option) => {
        const isSelected = activeValue === option.value;

        return (
          <button
            aria-pressed={isSelected}
            className={`${controlClasses.filterChip} ${isSelected ? selectedFilterChipClasses[option.tone] : controlClasses.filterChipInactive}`}
            key={option.value}
            onClick={() => onValueChange(option.value)}
            type="button"
          >
            <span>{option.label}</span>
            {option.count !== undefined ? (
              <span className={controlClasses.countBadge}>{option.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
