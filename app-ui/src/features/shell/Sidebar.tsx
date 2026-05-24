import { type CSSProperties } from "react";
import { Package } from "lucide-react";
import { ActionButton } from "../../components/ActionButton";
import { controlClasses, layoutClasses, shellClasses, textClasses } from "../../styles/componentClasses";
import { pillToneClasses } from "../../styles/toneClasses";
import { getProgressColor } from "./progress";
import type { NavItem } from "./types";

function getBadgeClasses(tone: NavItem["tone"]) {
  switch (tone) {
    case "pending":
      return pillToneClasses.pending;
    case "alert":
      return pillToneClasses.danger;
    case "accent":
      return pillToneClasses.accent;
    case "linked":
      return pillToneClasses.success;
    case "unlinked":
      return pillToneClasses.neutral;
  }
}

function ProgressFraction({ complete, total }: { complete: number; total: number }) {
  const color = getProgressColor((complete / total) * 100);
  const progressColorStyle: CSSProperties & Record<"--progress-color", string> = {
    "--progress-color": color,
  };

  return (
    <span className={`ml-auto flex shrink-0 items-baseline font-semibold tabular-nums ${textClasses.finePrint}`}>
      <span className={`${layoutClasses.progressDigit} text-right text-[var(--progress-color)]`} style={progressColorStyle}>
        {complete}
      </span>
      <span className="px-0.5 text-ctp-overlay1">/</span>
      <span className={`${layoutClasses.progressDigit} text-left text-ctp-subtext0`}>{total}</span>
    </span>
  );
}

function SidebarSection({
  activeItemId,
  emptyActionLabel,
  emptyMessage,
  items,
  onEmptyAction,
  onSelect,
  title,
}: {
  activeItemId: string;
  emptyActionLabel?: string;
  emptyMessage?: string;
  items: NavItem[];
  onEmptyAction?: () => void;
  onSelect: (itemId: string) => void;
  title: string;
}) {
  return (
    <section className={shellClasses.navSection}>
      <h2 className={`${shellClasses.navSectionTitle} ${textClasses.eyebrow} text-ctp-subtext0`}>
        {title}
      </h2>
      <div className={shellClasses.navStack}>
        {items.length === 0 && emptyMessage ? (
          <div className="space-y-2 px-3.5 py-2">
            <p className={textClasses.bodyMutedRelaxed}>{emptyMessage}</p>
            {emptyActionLabel && onEmptyAction ? (
              <ActionButton className={controlClasses.actionButtonCompact} onClick={onEmptyAction}>
                {emptyActionLabel}
              </ActionButton>
            ) : null}
          </div>
        ) : null}
        {items.map((item) => (
          <button
            key={item.id}
            className={`${shellClasses.navItem} ${
              item.id === activeItemId ? "bg-ctp-surface0 text-ctp-text" : "text-ctp-subtext1"
            }`}
            onClick={() => onSelect(item.id)}
            type="button"
          >
            <span className={`min-w-0 flex-1 truncate ${textClasses.navItem}`}>
              {item.label}
            </span>
            {item.progress ? (
              <ProgressFraction complete={item.progress.complete} total={item.progress.total} />
            ) : null}
            {item.badge !== undefined ? (
              <span className={`tabular-nums ${controlClasses.pill} ${shellClasses.navBadge} ${getBadgeClasses(item.tone)}`}>
                {item.badge}
              </span>
            ) : null}
          </button>
        ))}
      </div>
    </section>
  );
}

export function Sidebar({
  activeItemId,
  isSettingsMode,
  libraryItems,
  maintenanceItems,
  onConfigureSync,
  onHome,
  onSelect,
  playlistEmptyActionLabel,
  playlistEmptyMessage,
  playlistItems,
  settingsItems,
}: {
  activeItemId: string;
  isSettingsMode: boolean;
  libraryItems: NavItem[];
  maintenanceItems: NavItem[];
  onConfigureSync: () => void;
  onHome: () => void;
  onSelect: (itemId: string) => void;
  playlistEmptyActionLabel?: string;
  playlistEmptyMessage: string;
  playlistItems: NavItem[];
  settingsItems: NavItem[];
}) {
  return (
    <aside className={shellClasses.sidebar}>
      <div className={shellClasses.sidebarHeader}>
        <button
          className="flex w-full items-center gap-2.5 text-left transition-opacity hover:opacity-90"
          onClick={onHome}
          type="button"
        >
          <div className={shellClasses.sidebarLogo}>
            <Package aria-hidden="true" className="h-4 w-4" strokeWidth={1.7} />
          </div>
          <div>
            <p className={`${shellClasses.brandEyebrow} text-ctp-mauve`}>
              CRATELYNX
            </p>
            <p className={`mt-0.5 text-ctp-subtext0 ${textClasses.finePrint}`}>Playlist linking control room</p>
          </div>
        </button>
      </div>

      <div className={shellClasses.sidebarBody}>
        {isSettingsMode ? (
          <SidebarSection activeItemId={activeItemId} items={settingsItems} onSelect={onSelect} title="Settings" />
        ) : (
          <>
            <SidebarSection activeItemId={activeItemId} items={maintenanceItems} onSelect={onSelect} title="Maintenance" />
            <SidebarSection
              activeItemId={activeItemId}
              emptyActionLabel={playlistEmptyActionLabel}
              emptyMessage={playlistEmptyMessage}
              items={playlistItems}
              onEmptyAction={onConfigureSync}
              onSelect={onSelect}
              title="YouTube Music"
            />
            <SidebarSection activeItemId={activeItemId} items={libraryItems} onSelect={onSelect} title="Local Library" />
          </>
        )}
      </div>
    </aside>
  );
}
