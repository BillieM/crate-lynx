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

const baseClasses = "inline-flex min-h-10 items-center gap-2 rounded-full border px-4 text-[13px] font-semibold transition-colors";
const inactiveClasses =
  "border-ctp-surface1 bg-ctp-surface0 text-ctp-subtext0 hover:border-ctp-overlay0 hover:bg-ctp-surface1 hover:text-ctp-text";

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
            className={`${baseClasses} ${isSelected ? selectedFilterChipClasses[option.tone] : inactiveClasses}`}
            key={option.value}
            onClick={() => onValueChange(option.value)}
            type="button"
          >
            <span>{option.label}</span>
            {option.count !== undefined ? (
              <span
                className={`min-w-6 bg-ctp-mantle px-2 py-0.5 text-center tabular-nums text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1 ${controlClasses.pill}`}
              >
                {option.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
