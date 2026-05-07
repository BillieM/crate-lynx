import { X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef } from "react";

import { controlClasses, surfaceClasses, textClasses } from "../styles/componentClasses";

type DrawerProps = {
  children: ReactNode;
  onClose: () => void;
  open: boolean;
  title: string;
};

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function Drawer({ children, onClose, open, title }: DrawerProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    window.setTimeout(() => {
      const firstFocusable = panelRef.current?.querySelector<HTMLElement>(focusableSelector);
      (firstFocusable ?? panelRef.current)?.focus();
    }, 0);

    return () => {
      document.body.style.overflow = previousBodyOverflow;
      returnFocusRef.current?.focus();
      returnFocusRef.current = null;
    };
  }, [open]);

  if (!open) {
    return null;
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusable = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);

    if (focusable.length === 0) {
      event.preventDefault();
      panelRef.current?.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-50">
      <button
        aria-label="Close drawer"
        className="absolute inset-0 h-full w-full cursor-default bg-ctp-crust/55"
        type="button"
        onClick={onClose}
      />
      <div
        aria-labelledby={titleId}
        aria-modal="true"
        className={`absolute right-0 top-0 flex h-full w-full max-w-[34rem] flex-col border-l border-ctp-surface1 bg-ctp-base shadow-2xl shadow-ctp-crust/40 outline-none sm:w-[88vw] ${surfaceClasses.panelRadius}`}
        ref={panelRef}
        role="dialog"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-start justify-between gap-3 border-b border-ctp-surface0 px-4 py-3">
          <h2 className={textClasses.title} id={titleId}>
            {title}
          </h2>
          <button
            aria-label="Close drawer"
            className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} border-ctp-surface1 bg-ctp-surface0 text-ctp-text hover:bg-ctp-surface1`}
            type="button"
            onClick={onClose}
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
      </div>
    </div>
  );
}
