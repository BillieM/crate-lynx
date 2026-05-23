import { Copy, ExternalLink, GitBranch, Search, Unlink } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ActionButton } from "../../components/ActionButton";
import { Drawer } from "../../components/Drawer";
import { formatDuration, getMatchMethodLabel } from "../../lib/formatters";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { LocalTrackAudioPreview } from "../localTracks/LocalTrackAudioPreview";
import {
  type LocalTrackDetail,
  type LocalTrackSearchResult,
  type MetadataField,
  type StreamingTrackDetail,
  type StreamingTrackRelationship,
  type StreamingTrackSearchResult,
  type TrackDetailTarget,
  formatTrackDetailTarget,
  parseTrackDetailTarget,
  searchLocalTracks,
  searchStreamingTracks,
  useCreateFinalLinkMutation,
  useCreateStreamingRelationshipMutation,
  useDeleteFinalLinkMutation,
  useDeleteStreamingRelationshipMutation,
  useTrackDetailQuery,
  useUpdateStreamingRelationshipMutation,
} from "./queries";

type TrackDetailDrawerProps = {
  onClose?: () => void;
  open?: boolean;
  syncUrl?: boolean;
  target?: TrackDetailTarget | null;
};

type DetailTab = "summary" | "links" | "activity" | "metadata";

type RelationshipAction =
  | { kind: "delete"; relationship: StreamingTrackRelationship }
  | { kind: "update"; relationship: StreamingTrackRelationship; relationshipType: "equivalent" | "related" };

const tabLabels = {
  summary: "Summary",
  links: "Links",
  activity: "Activity",
  metadata: "Metadata",
} satisfies Record<DetailTab, string>;

const detailTabs: DetailTab[] = ["summary", "links", "activity", "metadata"];

const emptyMetadataFields: MetadataField[] = [];

export function TrackDetailDrawer({ onClose, open = false, syncUrl = false, target = null }: TrackDetailDrawerProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlTarget = parseTrackDetailTarget(searchParams.get("detail"));
  const effectiveTarget = syncUrl ? urlTarget : target;
  const effectiveOpen = open || (syncUrl && effectiveTarget !== null);
  const detailQuery = useTrackDetailQuery(effectiveTarget, effectiveOpen);
  const [activeTab, setActiveTab] = useState<DetailTab>("summary");
  const targetKey = effectiveTarget ? formatTrackDetailTarget(effectiveTarget) : "none";

  useEffect(() => {
    setActiveTab("summary");
  }, [targetKey]);

  function close() {
    if (syncUrl) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete("detail");
      setSearchParams(nextParams, { replace: true });
    }

    onClose?.();
  }

  function navigateTo(nextTarget: TrackDetailTarget) {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("detail", formatTrackDetailTarget(nextTarget));
    setSearchParams(nextParams, { replace: false });
    setActiveTab("summary");
  }

  const title = getDrawerTitle(effectiveTarget, detailQuery.data);

  return (
    <Drawer open={effectiveOpen} title={title} onClose={close}>
      {detailQuery.isLoading ? <p className={textClasses.caption}>Loading track detail...</p> : null}
      {detailQuery.isError ? <p className="text-[12px] font-medium text-ctp-red">Track detail could not be loaded.</p> : null}
      {effectiveTarget && detailQuery.data ? (
        <div className="grid gap-3">
          <div className="flex flex-wrap gap-1.5 border-b border-ctp-surface0 pb-2">
            {detailTabs.map((tab) => (
              <button
                className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} ${
                  activeTab === tab
                    ? "border-ctp-mauve bg-ctp-mauve/18 text-ctp-text"
                    : "border-ctp-surface1 bg-ctp-surface0 text-ctp-subtext0 hover:bg-ctp-surface1"
                }`}
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
              >
                {tabLabels[tab]}
              </button>
            ))}
          </div>
          {effectiveTarget.type === "local" ? (
            <LocalTrackDetailContent
              activeTab={activeTab}
              detail={detailQuery.data as LocalTrackDetail}
              onNavigate={navigateTo}
            />
          ) : (
            <StreamingTrackDetailContent
              activeTab={activeTab}
              detail={detailQuery.data as StreamingTrackDetail}
              onNavigate={navigateTo}
            />
          )}
        </div>
      ) : null}
    </Drawer>
  );
}

function LocalTrackDetailContent({
  activeTab,
  detail,
  onNavigate,
}: {
  activeTab: DetailTab;
  detail: LocalTrackDetail;
  onNavigate: (target: TrackDetailTarget) => void;
}) {
  if (activeTab === "summary") {
    const topSuggestion = detail.pending_suggestions[0] ?? null;

    return (
      <Section>
        <SummaryHeader
          badge={<StatusPill status={detail.link_status} />}
          subtitle={[detail.artist, detail.album].filter(Boolean).join(" / ") || "No Beets title metadata"}
          title={detail.title ?? filename(detail.file_path)}
        />
        <FieldGrid>
          <DetailField label="Local ID" value={detail.id} copyValue={String(detail.id)} />
          {detail.beets_id !== null ? <DetailField label="Beets ID" value={detail.beets_id} /> : null}
          {detail.duration_ms !== null ? <DetailField label="Duration" value={formatDuration(detail.duration_ms)} /> : null}
          <DetailField label="File path" value={displayFilePath(detail)} copyValue={detail.file_path} wide />
        </FieldGrid>
        <LocalTrackAudioPreview label={localTrackAudioLabel(detail)} localTrackId={detail.id} />
        <LinkStateSummary
          body={
            detail.final_link
              ? [detail.final_link.streaming_track.artist, detail.final_link.streaming_track.album].filter(Boolean).join(" / ")
              : topSuggestion
                ? `${detail.pending_suggestions.length} pending suggestion${detail.pending_suggestions.length === 1 ? "" : "s"}`
                : "No approved streaming link yet"
          }
          title={detail.final_link?.streaming_track.title ?? "Streaming link"}
        />
        {topSuggestion ? <LocalSuggestionCard onNavigate={onNavigate} suggestion={topSuggestion} /> : null}
      </Section>
    );
  }

  if (activeTab === "links") {
    return <LocalLinks detail={detail} onNavigate={onNavigate} />;
  }

  if (activeTab === "metadata") {
    return <LocalMetadata detail={detail} />;
  }

  return (
    <Section>
      <FieldGrid>
        <DetailField label="Created" value={formatTimestamp(detail.created_at)} />
        <DetailField label="Updated" value={formatTimestamp(detail.updated_at)} />
      </FieldGrid>
      <HistoryList attempts={detail.failed_ingestion_attempts} />
    </Section>
  );
}

function StreamingTrackDetailContent({
  activeTab,
  detail,
  onNavigate,
}: {
  activeTab: DetailTab;
  detail: StreamingTrackDetail;
  onNavigate: (target: TrackDetailTarget) => void;
}) {
  if (activeTab === "summary") {
    const topSuggestion = detail.pending_local_suggestions[0] ?? null;
    const relationshipCount = detail.relationships.length;
    const playlistCount = detail.playlist_appearances.length;

    return (
      <Section>
        <SummaryHeader
          action={
            <a
              className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5 border-ctp-surface1 bg-ctp-surface0 text-ctp-text hover:bg-ctp-surface1`}
              href={`https://music.youtube.com/watch?v=${encodeURIComponent(detail.provider_track_id)}`}
              rel="noreferrer"
              target="_blank"
            >
              <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
              Open
            </a>
          }
          badge={<StatusPill status={detail.resolved_local_link ? "linked" : topSuggestion ? "pending" : "unlinked"} />}
          subtitle={[detail.artist, detail.album].filter(Boolean).join(" / ") || "Streaming metadata"}
          title={detail.title}
        />
        <FieldGrid>
          <DetailField label="Provider ID" value={detail.provider_track_id} copyValue={detail.provider_track_id} />
          {detail.duration_ms !== null ? <DetailField label="Duration" value={formatDuration(detail.duration_ms)} /> : null}
          {detail.year !== null ? <DetailField label="Year" value={detail.year} /> : null}
          {detail.isrc ? <DetailField label="ISRC" value={detail.isrc} copyValue={detail.isrc} /> : null}
          <DetailField label="Playlist appearances" value={playlistCount} />
          <DetailField label="Relationships" value={relationshipCount} />
        </FieldGrid>
        <LinkStateSummary
          body={
            detail.resolved_local_link
              ? [
                  detail.resolved_local_link.local_track.artist,
                  detail.resolved_local_link.local_track.album,
                  formatResolutionSource(detail.resolved_local_link.resolution_source),
                ]
                  .filter(Boolean)
                  .join(" / ")
              : topSuggestion
                ? `${detail.pending_local_suggestions.length} pending local suggestion${
                    detail.pending_local_suggestions.length === 1 ? "" : "s"
                  }`
                : "No local file currently resolves for this track"
          }
          title={
            detail.resolved_local_link
              ? (detail.resolved_local_link.local_track.title ?? filename(detail.resolved_local_link.local_track.file_path))
              : "Local link"
          }
        />
        {topSuggestion ? <StreamingLocalSuggestionCard onNavigate={onNavigate} suggestion={topSuggestion} /> : null}
      </Section>
    );
  }

  if (activeTab === "links") {
    return <StreamingLinks detail={detail} onNavigate={onNavigate} />;
  }

  if (activeTab === "metadata") {
    return (
      <Section>
        <FieldGrid>
          <DetailField label="Title" value={detail.title} />
          <DetailField label="Artist" value={detail.artist} />
          <DetailField label="Album" value={detail.album ?? "Unavailable"} />
          <DetailField label="Provider ID" value={detail.provider_track_id} copyValue={detail.provider_track_id} wide />
          <DetailField label="ISRC" value={detail.isrc ?? "Unavailable"} />
          <DetailField label="Duration" value={formatDuration(detail.duration_ms)} />
        </FieldGrid>
      </Section>
    );
  }

  return (
    <Section>
      <p className={textClasses.label}>
        Playlist appearances {detail.playlist_appearances.length > 0 ? `(${detail.playlist_appearances.length})` : ""}
      </p>
      {detail.playlist_appearances.length > 0 ? (
        <ul className="grid gap-2">
          {detail.playlist_appearances.map((appearance) => (
            <li className={surfaceClasses.insetPanel} key={`${appearance.playlist_id}-${appearance.position}`}>
              <div className="grid gap-1 px-3 py-2">
                <p className={textClasses.label}>{appearance.title}</p>
                <p className={`${textClasses.caption} tabular-nums`}>
                  Position {appearance.position} / {formatSyncMode(appearance.sync_mode)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className={textClasses.caption}>No imported playlist appearances.</p>
      )}
    </Section>
  );
}

function LocalLinks({
  detail,
  onNavigate,
}: {
  detail: LocalTrackDetail;
  onNavigate: (target: TrackDetailTarget) => void;
}) {
  const createFinalLink = useCreateFinalLinkMutation();
  const deleteFinalLink = useDeleteFinalLinkMutation();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [selectedStreamingTrack, setSelectedStreamingTrack] = useState<StreamingTrackSearchResult | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setConfirmRemove(false);
    setSelectedStreamingTrack(null);
    setShowPicker(false);
    setStatus(null);
  }, [detail.id]);

  function confirmStreamingLink() {
    if (!selectedStreamingTrack) {
      return;
    }

    setStatus(null);
    createFinalLink.mutate(
      {
        local_track_id: detail.id,
        replace_final_link_id: detail.final_link?.id ?? null,
        streaming_track_id: selectedStreamingTrack.id,
      },
      {
        onError: () => setStatus("Link update failed. Check for conflicting links in the target equivalent group."),
        onSuccess: () => {
          setSelectedStreamingTrack(null);
          setShowPicker(false);
          setStatus("Link updated.");
        },
      },
    );
  }

  function confirmRemoveLink() {
    if (!detail.final_link) {
      return;
    }

    setStatus(null);
    deleteFinalLink.mutate(detail.final_link.id, {
      onError: () => setStatus("Remove failed."),
      onSuccess: () => {
        setConfirmRemove(false);
        setStatus("Link removed.");
      },
    });
  }

  return (
    <Section>
      <LocalTrackAudioPreview label={localTrackAudioLabel(detail)} localTrackId={detail.id} />
      {detail.final_link ? (
        <div className={surfaceClasses.insetPanel}>
          <div className="grid gap-3 px-3 py-2.5">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className={textClasses.label}>{detail.final_link.streaming_track.title}</p>
                <p className={`${textClasses.caption} truncate`}>
                  {detail.final_link.streaming_track.artist} / Final link {detail.final_link.id}
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <ActionButton
                  className={controlClasses.actionButtonCompact}
                  onClick={() => onNavigate({ id: detail.final_link?.streaming_track_id ?? 0, type: "streaming" })}
                >
                  Open streaming
                </ActionButton>
                <ActionButton
                  className={controlClasses.actionButtonCompact}
                  disabled={deleteFinalLink.isPending}
                  tone="danger"
                  onClick={() => setConfirmRemove(true)}
                >
                  <Unlink aria-hidden="true" className="h-3.5 w-3.5" />
                  Remove link
                </ActionButton>
              </div>
            </div>
            {confirmRemove ? (
              <ConfirmAction
                confirmLabel="Confirm remove link"
                disabled={deleteFinalLink.isPending}
                message="Remove the approved link from this local track?"
                onCancel={() => setConfirmRemove(false)}
                onConfirm={confirmRemoveLink}
                tone="danger"
              />
            ) : null}
          </div>
        </div>
      ) : (
        <p className={textClasses.caption}>No final local-to-streaming link has been approved yet.</p>
      )}

      <DisclosurePanel
        actionLabel={detail.final_link ? "Change streaming link" : "Add streaming link"}
        open={showPicker}
        onToggle={() => {
          setSelectedStreamingTrack(null);
          setShowPicker((current) => !current);
        }}
      >
        <StreamingSearchPicker label="Search streaming tracks" onSelect={setSelectedStreamingTrack} />
        {selectedStreamingTrack ? (
          <SelectionPreview
            confirmLabel={detail.final_link ? "Confirm link change" : "Confirm streaming link"}
            disabled={createFinalLink.isPending}
            subtitle={[selectedStreamingTrack.artist, selectedStreamingTrack.album].filter(Boolean).join(" / ")}
            title={selectedStreamingTrack.title}
            onCancel={() => setSelectedStreamingTrack(null)}
            onConfirm={confirmStreamingLink}
          />
        ) : null}
      </DisclosurePanel>

      {detail.pending_suggestions.length > 0 ? (
        <div className="grid gap-2">
          <p className={textClasses.label}>Pending suggestions ({detail.pending_suggestions.length})</p>
          {detail.pending_suggestions.map((suggestion) => (
            <LocalSuggestionCard key={suggestion.id} onNavigate={onNavigate} suggestion={suggestion} />
          ))}
        </div>
      ) : null}
      <MutationStatus status={status} />
    </Section>
  );
}

function StreamingLinks({
  detail,
  onNavigate,
}: {
  detail: StreamingTrackDetail;
  onNavigate: (target: TrackDetailTarget) => void;
}) {
  const createFinalLink = useCreateFinalLinkMutation();
  const createRelationship = useCreateStreamingRelationshipMutation();
  const updateRelationship = useUpdateStreamingRelationshipMutation();
  const deleteRelationship = useDeleteStreamingRelationshipMutation();
  const deleteFinalLink = useDeleteFinalLinkMutation();
  const [confirmLocalRemove, setConfirmLocalRemove] = useState(false);
  const [pendingRelationshipAction, setPendingRelationshipAction] = useState<RelationshipAction | null>(null);
  const [relationshipType, setRelationshipType] = useState<"equivalent" | "related">("equivalent");
  const [selectedLocalTrack, setSelectedLocalTrack] = useState<LocalTrackSearchResult | null>(null);
  const [selectedStreamingPeer, setSelectedStreamingPeer] = useState<StreamingTrackSearchResult | null>(null);
  const [showLocalPicker, setShowLocalPicker] = useState(false);
  const [showRelationshipPicker, setShowRelationshipPicker] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setConfirmLocalRemove(false);
    setPendingRelationshipAction(null);
    setSelectedLocalTrack(null);
    setSelectedStreamingPeer(null);
    setShowLocalPicker(false);
    setShowRelationshipPicker(false);
    setStatus(null);
  }, [detail.id]);

  function confirmLocalLink() {
    if (!selectedLocalTrack) {
      return;
    }

    setStatus(null);
    createFinalLink.mutate(
      {
        local_track_id: selectedLocalTrack.id,
        replace_final_link_id:
          detail.resolved_local_link?.source_streaming_track_id === detail.id
            ? detail.resolved_local_link.final_link_id
            : null,
        streaming_track_id: detail.id,
      },
      {
        onError: () => setStatus("Link update failed. Check for conflicting local or equivalent links."),
        onSuccess: () => {
          setSelectedLocalTrack(null);
          setShowLocalPicker(false);
          setStatus("Link updated.");
        },
      },
    );
  }

  function confirmRemoveLocalLink() {
    if (!detail.resolved_local_link || detail.resolved_local_link.source_streaming_track_id !== detail.id) {
      return;
    }

    setStatus(null);
    deleteFinalLink.mutate(detail.resolved_local_link.final_link_id, {
      onError: () => setStatus("Remove failed."),
      onSuccess: () => {
        setConfirmLocalRemove(false);
        setStatus("Link removed.");
      },
    });
  }

  function confirmRelationshipCreate() {
    if (!selectedStreamingPeer) {
      return;
    }

    setStatus(null);
    createRelationship.mutate(
      {
        first_track_id: detail.id,
        relationship_type: relationshipType,
        second_track_id: selectedStreamingPeer.id,
      },
      {
        onError: () => setStatus("Relationship create failed. Equivalent conflicts may need resolving in the queue."),
        onSuccess: () => {
          setSelectedStreamingPeer(null);
          setShowRelationshipPicker(false);
          setStatus("Relationship added.");
        },
      },
    );
  }

  function confirmRelationshipAction() {
    if (!pendingRelationshipAction) {
      return;
    }

    setStatus(null);

    if (pendingRelationshipAction.kind === "delete") {
      deleteRelationship.mutate(pendingRelationshipAction.relationship.id, {
        onError: () => setStatus("Relationship delete failed."),
        onSuccess: () => {
          setPendingRelationshipAction(null);
          setStatus("Relationship removed.");
        },
      });
      return;
    }

    updateRelationship.mutate(
      {
        relationship_id: pendingRelationshipAction.relationship.id,
        relationship_type: pendingRelationshipAction.relationshipType,
      },
      {
        onError: () => setStatus("Relationship update failed."),
        onSuccess: () => {
          setPendingRelationshipAction(null);
          setStatus("Relationship updated.");
        },
      },
    );
  }

  return (
    <Section>
      <div className="grid gap-2">
        <p className={textClasses.label}>Local link</p>
        {detail.resolved_local_link ? (
          <div className={`${surfaceClasses.insetPanel} px-3 py-2.5`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className={`${textClasses.caption} font-medium text-ctp-text`}>
                  {detail.resolved_local_link.local_track.title ?? filename(detail.resolved_local_link.local_track.file_path)}
                </p>
                <p className={`${textClasses.finePrint} text-ctp-subtext0`}>
                  {detail.resolved_local_link.resolution_source} via streaming #{detail.resolved_local_link.source_streaming_track_id}
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <ActionButton
                  className={controlClasses.actionButtonCompact}
                  onClick={() => onNavigate({ id: detail.resolved_local_link?.local_track_id ?? 0, type: "local" })}
                >
                  Open local
                </ActionButton>
                {detail.resolved_local_link.source_streaming_track_id === detail.id ? (
                  <ActionButton
                    className={controlClasses.actionButtonCompact}
                    disabled={deleteFinalLink.isPending}
                    tone="danger"
                    onClick={() => setConfirmLocalRemove(true)}
                  >
                    <Unlink aria-hidden="true" className="h-3.5 w-3.5" />
                    Remove link
                  </ActionButton>
                ) : null}
              </div>
            </div>
            {confirmLocalRemove ? (
              <ConfirmAction
                confirmLabel="Confirm remove link"
                disabled={deleteFinalLink.isPending}
                message="Remove the approved local link from this streaming track?"
                onCancel={() => setConfirmLocalRemove(false)}
                onConfirm={confirmRemoveLocalLink}
                tone="danger"
              />
            ) : null}
            <LocalTrackAudioPreview
              label={localTrackAudioLabel(detail.resolved_local_link.local_track)}
              localTrackId={detail.resolved_local_link.local_track_id}
            />
          </div>
        ) : (
          <p className={textClasses.caption}>No local file currently resolves for this streaming track.</p>
        )}
        <DisclosurePanel
          actionLabel={detail.resolved_local_link ? "Change local link" : "Add local link"}
          open={showLocalPicker}
          onToggle={() => {
            setSelectedLocalTrack(null);
            setShowLocalPicker((current) => !current);
          }}
        >
          <LocalSearchPicker label="Search local tracks" onSelect={setSelectedLocalTrack} />
          {selectedLocalTrack ? (
            <SelectionPreview
              confirmLabel={detail.resolved_local_link ? "Confirm local link change" : "Confirm local link"}
              disabled={createFinalLink.isPending}
              subtitle={[selectedLocalTrack.artist, selectedLocalTrack.album, displayFilePath(selectedLocalTrack)]
                .filter(Boolean)
                .join(" / ")}
              title={selectedLocalTrack.title ?? filename(selectedLocalTrack.file_path)}
              onCancel={() => setSelectedLocalTrack(null)}
              onConfirm={confirmLocalLink}
            >
              <LocalTrackAudioPreview label={localTrackAudioLabel(selectedLocalTrack)} localTrackId={selectedLocalTrack.id} />
            </SelectionPreview>
          ) : null}
        </DisclosurePanel>
      </div>

      <div className="grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className={textClasses.label}>Streaming relationships ({detail.relationships.length})</p>
        </div>
        <DisclosurePanel
          actionLabel="Add relationship"
          open={showRelationshipPicker}
          onToggle={() => {
            setSelectedStreamingPeer(null);
            setShowRelationshipPicker((current) => !current);
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <GitBranch aria-hidden="true" className="h-3.5 w-3.5 text-ctp-subtext0" />
            <label className="grid gap-1 text-[12px] font-medium text-ctp-subtext0">
              Relationship type
              <select
                className={`${controlClasses.controlRadius} border border-ctp-surface1 bg-ctp-surface0 px-2 py-1 text-[12px] text-ctp-text`}
                value={relationshipType}
                onChange={(event) => setRelationshipType(event.target.value as "equivalent" | "related")}
              >
                <option value="equivalent">Equivalent</option>
                <option value="related">Related</option>
              </select>
            </label>
          </div>
          <StreamingSearchPicker
            excludeTrackId={detail.id}
            label="Search streaming tracks"
            onSelect={setSelectedStreamingPeer}
          />
          {selectedStreamingPeer ? (
            <SelectionPreview
              confirmLabel="Confirm relationship"
              disabled={createRelationship.isPending}
              subtitle={[selectedStreamingPeer.artist, selectedStreamingPeer.album, titleCase(relationshipType)]
                .filter(Boolean)
                .join(" / ")}
              title={selectedStreamingPeer.title}
              onCancel={() => setSelectedStreamingPeer(null)}
              onConfirm={confirmRelationshipCreate}
            />
          ) : null}
        </DisclosurePanel>
        {detail.relationships.length > 0 ? (
          <ul className="grid gap-2">
            {detail.relationships.map((relationship) => (
              <li className={`${surfaceClasses.insetPanel} px-3 py-2`} key={relationship.id}>
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className={`${textClasses.caption} font-medium text-ctp-text`}>{relationship.peer_track.title}</p>
                      <p className={`${textClasses.finePrint} text-ctp-subtext0`}>
                        {relationship.peer_track.artist} / {titleCase(relationship.relationship_type)}
                      </p>
                    </div>
                    <ActionButton
                      className={controlClasses.actionButtonCompact}
                      onClick={() => onNavigate({ id: relationship.peer_track.id, type: "streaming" })}
                    >
                      Open peer
                    </ActionButton>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <ActionButton
                      className={controlClasses.actionButtonCompact}
                      disabled={updateRelationship.isPending || relationship.relationship_type === "equivalent"}
                      onClick={() =>
                        setPendingRelationshipAction({
                          kind: "update",
                          relationship,
                          relationshipType: "equivalent",
                        })
                      }
                    >
                      Make equivalent
                    </ActionButton>
                    <ActionButton
                      className={controlClasses.actionButtonCompact}
                      disabled={updateRelationship.isPending || relationship.relationship_type === "related"}
                      onClick={() =>
                        setPendingRelationshipAction({
                          kind: "update",
                          relationship,
                          relationshipType: "related",
                        })
                      }
                    >
                      Make related
                    </ActionButton>
                    <ActionButton
                      className={controlClasses.actionButtonCompact}
                      disabled={deleteRelationship.isPending}
                      tone="danger"
                      onClick={() => setPendingRelationshipAction({ kind: "delete", relationship })}
                    >
                      Delete relationship
                    </ActionButton>
                  </div>
                  {pendingRelationshipAction?.relationship.id === relationship.id ? (
                    <ConfirmAction
                      confirmLabel={
                        pendingRelationshipAction.kind === "delete"
                          ? "Confirm delete relationship"
                          : `Confirm ${pendingRelationshipAction.relationshipType} relationship`
                      }
                      disabled={deleteRelationship.isPending || updateRelationship.isPending}
                      message={
                        pendingRelationshipAction.kind === "delete"
                          ? `Delete the relationship with ${relationship.peer_track.title}?`
                          : `Change this relationship to ${pendingRelationshipAction.relationshipType}?`
                      }
                      onCancel={() => setPendingRelationshipAction(null)}
                      onConfirm={confirmRelationshipAction}
                      tone={pendingRelationshipAction.kind === "delete" ? "danger" : "neutral"}
                    />
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className={textClasses.caption}>No accepted streaming-to-streaming relationships yet.</p>
        )}
      </div>

      {detail.pending_local_suggestions.length > 0 ? (
        <div className="grid gap-2">
          <p className={textClasses.label}>Pending local suggestions ({detail.pending_local_suggestions.length})</p>
          {detail.pending_local_suggestions.map((suggestion) => (
            <StreamingLocalSuggestionCard key={suggestion.id} onNavigate={onNavigate} suggestion={suggestion} />
          ))}
        </div>
      ) : null}
      <MutationStatus status={status} />
    </Section>
  );
}

function LocalMetadata({ detail }: { detail: LocalTrackDetail }) {
  const [query, setQuery] = useState("");
  const [showEmpty, setShowEmpty] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const rawSections = useMemo(
    () => [
      { fields: detail.beets_item?.fields ?? emptyMetadataFields, title: "Raw Beets item fields" },
      { fields: detail.beets_item?.attributes ?? emptyMetadataFields, title: "Raw Beets item attributes" },
      { fields: detail.beets_album?.fields ?? emptyMetadataFields, title: "Raw Beets album fields" },
      { fields: detail.beets_album?.attributes ?? emptyMetadataFields, title: "Raw Beets album attributes" },
    ],
    [detail],
  );
  const curatedSections = useMemo(() => buildMetadataSections(detail), [detail]);

  return (
    <Section>
      {curatedSections.map((section) => (
        <MetadataSection fields={section.fields} key={section.title} query="" showEmpty title={section.title} />
      ))}
      <FingerprintDiagnostic fingerprint={detail.fingerprint} />
      <label className="inline-flex items-center gap-1.5 text-[12px] text-ctp-subtext0">
        <input
          checked={showRaw}
          className="h-3.5 w-3.5 accent-ctp-mauve"
          type="checkbox"
          onChange={(event) => setShowRaw(event.target.checked)}
        />
        Show raw fields
      </label>
      {showRaw ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <label className={`${controlClasses.searchFrame} flex min-w-[14rem] flex-1 items-center gap-2 px-2.5 py-1.5`}>
              <Search aria-hidden="true" className="h-3.5 w-3.5 text-ctp-subtext0" />
              <input
                aria-label="Search metadata fields"
                className="min-w-0 flex-1 bg-transparent text-[12px] text-ctp-text outline-none placeholder:text-ctp-overlay1"
                placeholder="Search fields"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <label className="inline-flex items-center gap-1.5 text-[12px] text-ctp-subtext0">
              <input
                checked={showEmpty}
                className="h-3.5 w-3.5 accent-ctp-mauve"
                type="checkbox"
                onChange={(event) => setShowEmpty(event.target.checked)}
              />
              Show empty fields
            </label>
          </div>
          {rawSections.map((section) => (
            <MetadataSection
              fields={section.fields}
              key={section.title}
              query={query}
              showEmpty={showEmpty}
              title={section.title}
            />
          ))}
        </>
      ) : null}
    </Section>
  );
}

function MetadataSection({
  fields,
  query,
  showEmpty,
  title,
}: {
  fields: MetadataField[];
  query: string;
  showEmpty: boolean;
  title: string;
}) {
  const normalizedQuery = query.trim().toLowerCase();
  const visibleFields = fields.filter((field) => {
    if (!showEmpty && (field.value === null || field.value === "")) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return `${field.key} ${field.value ?? ""}`.toLowerCase().includes(normalizedQuery);
  });

  return (
    <div className="grid gap-2">
      <p className={textClasses.label}>{title}</p>
      {visibleFields.length > 0 ? (
        <dl className="grid gap-1.5">
          {visibleFields.map((field) => (
            <div className="grid grid-cols-[minmax(7rem,12rem)_minmax(0,1fr)] gap-2 text-[12px]" key={field.key}>
              <dt className="truncate font-medium text-ctp-overlay1">{field.key}</dt>
              <dd className="min-w-0 break-words text-ctp-text">{field.value ?? "Empty"}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className={textClasses.caption}>No matching fields.</p>
      )}
    </div>
  );
}

function SummaryHeader({
  action,
  badge,
  subtitle,
  title,
}: {
  action?: ReactNode;
  badge?: ReactNode;
  subtitle: string;
  title: string;
}) {
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className={textClasses.sectionTitle}>{title}</h3>
            {badge}
          </div>
          <p className={textClasses.bodyMuted}>{subtitle}</p>
        </div>
        {action}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const normalizedStatus = status.toLowerCase();
  const toneClasses =
    normalizedStatus === "linked"
      ? "bg-ctp-green/18 text-ctp-green ring-ctp-green/35"
      : normalizedStatus === "pending"
        ? "bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/35"
        : "bg-ctp-pink/18 text-ctp-pink ring-ctp-pink/35";

  return (
    <span className={`${controlClasses.pill} ${toneClasses} ring-1 ring-inset`}>{titleCase(normalizedStatus)}</span>
  );
}

function LinkStateSummary({ body, title }: { body: string; title: string }) {
  return (
    <div className={`${surfaceClasses.insetPanel} px-3 py-2.5`}>
      <p className={`${textClasses.caption} font-medium text-ctp-text`}>{title}</p>
      <p className={textClasses.caption}>{body}</p>
    </div>
  );
}

function LocalSuggestionCard({
  onNavigate,
  suggestion,
}: {
  onNavigate: (target: TrackDetailTarget) => void;
  suggestion: LocalTrackDetail["pending_suggestions"][number];
}) {
  return (
    <SuggestionCard
      actionLabel="Open streaming suggestion"
      label="Suggested streaming match"
      score={suggestion.score}
      subtitle={[suggestion.streaming_track.artist, suggestion.streaming_track.album].filter(Boolean).join(" / ")}
      title={suggestion.streaming_track.title}
      method={suggestion.match_method}
      onOpen={() => onNavigate({ id: suggestion.streaming_track_id, type: "streaming" })}
    />
  );
}

function StreamingLocalSuggestionCard({
  onNavigate,
  suggestion,
}: {
  onNavigate: (target: TrackDetailTarget) => void;
  suggestion: StreamingTrackDetail["pending_local_suggestions"][number];
}) {
  return (
    <SuggestionCard
      actionLabel="Open local suggestion"
      label="Suggested local match"
      score={suggestion.score}
      subtitle={[
        suggestion.local_track.artist,
        suggestion.local_track.album,
        displayFilePath(suggestion.local_track),
      ]
        .filter(Boolean)
        .join(" / ")}
      title={suggestion.local_track.title ?? filename(suggestion.local_track.file_path)}
      method={suggestion.match_method}
      onOpen={() => onNavigate({ id: suggestion.local_track_id, type: "local" })}
    >
      <LocalTrackAudioPreview label={localTrackAudioLabel(suggestion.local_track)} localTrackId={suggestion.local_track_id} />
    </SuggestionCard>
  );
}

function SuggestionCard({
  actionLabel,
  children,
  label,
  method,
  onOpen,
  score,
  subtitle,
  title,
}: {
  actionLabel: string;
  children?: ReactNode;
  label: string;
  method: string;
  onOpen: () => void;
  score: number;
  subtitle: string;
  title: string;
}) {
  return (
    <div className={`${surfaceClasses.insetPanel} px-3 py-2`}>
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className={textClasses.finePrint}>{label}</p>
            <p className={`${textClasses.caption} font-medium text-ctp-text`}>{title}</p>
            {subtitle ? <p className={`${textClasses.finePrint} truncate text-ctp-subtext0`}>{subtitle}</p> : null}
            <p className={`${textClasses.finePrint} text-ctp-subtext0`}>{getMatchMethodLabel(method)}</p>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`${controlClasses.countBadge} text-ctp-text`}>{Math.round(score * 100)}%</span>
            <ActionButton className={controlClasses.actionButtonCompact} onClick={onOpen}>
              {actionLabel}
            </ActionButton>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

function DisclosurePanel({
  actionLabel,
  children,
  onToggle,
  open,
}: {
  actionLabel: string;
  children: ReactNode;
  onToggle: () => void;
  open: boolean;
}) {
  return (
    <div className="grid gap-2">
      <ActionButton className={controlClasses.actionButtonCompact} onClick={onToggle}>
        {open ? "Cancel" : actionLabel}
      </ActionButton>
      {open ? <div className="grid gap-2">{children}</div> : null}
    </div>
  );
}

function SelectionPreview({
  children,
  confirmLabel,
  disabled,
  onCancel,
  onConfirm,
  subtitle,
  title,
}: {
  children?: ReactNode;
  confirmLabel: string;
  disabled?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  subtitle: string;
  title: string;
}) {
  return (
    <div className={`${surfaceClasses.insetPanel} grid gap-2 px-3 py-2`}>
      <div className="min-w-0">
        <p className={textClasses.finePrint}>Selected candidate</p>
        <p className={`${textClasses.caption} font-medium text-ctp-text`}>{title}</p>
        {subtitle ? <p className={`${textClasses.finePrint} truncate text-ctp-subtext0`}>{subtitle}</p> : null}
      </div>
      {children}
      <div className="flex flex-wrap gap-1.5">
        <ActionButton className={controlClasses.actionButtonCompact} disabled={disabled} onClick={onConfirm}>
          {confirmLabel}
        </ActionButton>
        <ActionButton className={controlClasses.actionButtonCompact} onClick={onCancel}>
          Clear
        </ActionButton>
      </div>
    </div>
  );
}

function ConfirmAction({
  confirmLabel,
  disabled,
  message,
  onCancel,
  onConfirm,
  tone = "neutral",
}: {
  confirmLabel: string;
  disabled?: boolean;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
  tone?: "danger" | "neutral";
}) {
  return (
    <div className="grid gap-2 rounded-[8px] border border-ctp-surface1 bg-ctp-mantle/70 px-3 py-2">
      <p className={textClasses.caption}>{message}</p>
      <div className="flex flex-wrap gap-1.5">
        <ActionButton className={controlClasses.actionButtonCompact} disabled={disabled} tone={tone} onClick={onConfirm}>
          {confirmLabel}
        </ActionButton>
        <ActionButton className={controlClasses.actionButtonCompact} onClick={onCancel}>
          Cancel
        </ActionButton>
      </div>
    </div>
  );
}

function FingerprintDiagnostic({ fingerprint }: { fingerprint: string | null }) {
  const [revealed, setRevealed] = useState(false);

  return (
    <div className="grid gap-2">
      <p className={textClasses.label}>Advanced diagnostics</p>
      <div className={`${surfaceClasses.insetPanel} grid gap-2 px-3 py-2.5`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className={`${textClasses.caption} font-medium text-ctp-text`}>Fingerprint present</p>
            <p className={textClasses.finePrint}>{fingerprint ? "Stored acoustic fingerprint" : "No fingerprint stored"}</p>
          </div>
          <span
            className={`${controlClasses.pill} ${
              fingerprint
                ? "bg-ctp-green/18 text-ctp-green ring-ctp-green/35"
                : "bg-ctp-surface0 text-ctp-subtext0 ring-ctp-surface1"
            } ring-1 ring-inset`}
          >
            {fingerprint ? "Yes" : "No"}
          </span>
        </div>
        {fingerprint ? (
          <>
            <p className={`${textClasses.finePrint} break-all text-ctp-subtext0`}>
              {revealed ? fingerprint : truncateMiddle(fingerprint, 96)}
            </p>
            <div className="flex flex-wrap gap-1.5">
              <ActionButton className={controlClasses.actionButtonCompact} onClick={() => setRevealed((current) => !current)}>
                {revealed ? "Hide fingerprint" : "Reveal fingerprint"}
              </ActionButton>
              <ActionButton
                className={controlClasses.actionButtonCompact}
                onClick={() => {
                  void navigator.clipboard?.writeText(fingerprint);
                }}
              >
                Copy fingerprint
              </ActionButton>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

function buildMetadataSections(detail: LocalTrackDetail): { fields: MetadataField[]; title: string }[] {
  const fields = collectMetadataFields(detail).filter(isUsefulMetadataField);
  const usedKeys = new Set<string>();

  function fieldsFor(keys: string[]) {
    return keys.flatMap((key) => {
      if (usedKeys.has(key)) {
        return [];
      }

      const field = fields.find((candidate) => candidate.key === key);
      if (!field) {
        return [];
      }

      usedKeys.add(key);
      return [field];
    });
  }

  return [
    {
      fields: fieldsFor(["title", "artist", "album", "albumartist", "genre", "year", "track", "tracktotal", "bpm", "initial_key", "label"]),
      title: "Core metadata",
    },
    {
      fields: fieldsFor(["length", "format", "bitrate", "bitrate_mode", "samplerate", "bitdepth", "channels"]),
      title: "Audio",
    },
    {
      fields: fieldsFor(["isrc", "mb_trackid", "mb_artistid", "mb_albumid", "mb_releasegroupid", "discogs_albumid", "discogs_artistid", "discogs_labelid"]),
      title: "External IDs",
    },
    {
      fields: fieldsFor(["added", "mtime", "original_year", "original_month", "original_day"]),
      title: "Timestamps",
    },
  ].filter((section) => section.fields.length > 0);
}

function collectMetadataFields(detail: LocalTrackDetail): MetadataField[] {
  return [
    ...(detail.beets_item?.fields ?? []),
    ...(detail.beets_item?.attributes ?? []),
    ...(detail.beets_album?.fields ?? []),
    ...(detail.beets_album?.attributes ?? []),
  ];
}

function isUsefulMetadataField(field: MetadataField) {
  if (field.value === null) {
    return false;
  }

  const value = field.value.trim();
  const normalizedValue = value.toLowerCase();
  const normalizedKey = field.key.toLowerCase();

  if (!value || ["0", "0.0", "false"].includes(normalizedValue)) {
    return false;
  }

  if (["path", "comments"].includes(normalizedKey)) {
    return false;
  }

  if (["artists", "artist_sort", "artists_sort", "artist_credit", "artists_credit"].includes(normalizedKey)) {
    return false;
  }

  return true;
}

function StreamingSearchPicker({
  excludeTrackId,
  label,
  onSelect,
}: {
  excludeTrackId?: number;
  label: string;
  onSelect: (track: StreamingTrackSearchResult) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<StreamingTrackSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  async function runSearch() {
    setIsSearching(true);
    const response = await searchStreamingTracks(query);
    setResults(response.tracks.filter((track) => track.id !== excludeTrackId));
    setIsSearching(false);
  }

  return (
    <SearchPickerFrame
      isSearching={isSearching}
      label={label}
      query={query}
      onQueryChange={setQuery}
      onSearch={runSearch}
    >
      {results.map((track) => (
        <SearchResultButton key={track.id} onClick={() => onSelect(track)}>
          <span className="truncate font-medium">{track.title}</span>
          <span className="truncate text-ctp-subtext0">{track.artist}</span>
          {track.album ? <span className="truncate text-ctp-overlay1">{track.album}</span> : null}
        </SearchResultButton>
      ))}
    </SearchPickerFrame>
  );
}

function LocalSearchPicker({
  label,
  onSelect,
}: {
  label: string;
  onSelect: (track: LocalTrackSearchResult) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LocalTrackSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  async function runSearch() {
    setIsSearching(true);
    const response = await searchLocalTracks(query);
    setResults(response.tracks);
    setIsSearching(false);
  }

  return (
    <SearchPickerFrame
      isSearching={isSearching}
      label={label}
      query={query}
      onQueryChange={setQuery}
      onSearch={runSearch}
    >
      {results.map((track) => (
        <LocalSearchResultCard key={track.id} track={track} onSelect={onSelect} />
      ))}
    </SearchPickerFrame>
  );
}

function LocalSearchResultCard({
  onSelect,
  track,
}: {
  onSelect: (track: LocalTrackSearchResult) => void;
  track: LocalTrackSearchResult;
}) {
  return (
    <div className={`${surfaceClasses.insetPanel} grid min-w-0 gap-2 px-3 py-2 text-[12px] text-ctp-text`}>
      <div className="grid min-w-0 gap-0.5">
        <span className="truncate font-medium">{track.title ?? filename(track.file_path)}</span>
        <span className="truncate text-ctp-subtext0">{track.artist ?? track.file_path}</span>
        <span className="truncate text-ctp-overlay1">{track.album ?? displayFilePath(track)}</span>
      </div>
      <LocalTrackAudioPreview label={localTrackAudioLabel(track)} localTrackId={track.id} />
      <div>
        <ActionButton className={controlClasses.actionButtonCompact} onClick={() => onSelect(track)}>
          Select local track
        </ActionButton>
      </div>
    </div>
  );
}

function SearchPickerFrame({
  children,
  isSearching,
  label,
  onQueryChange,
  onSearch,
  query,
}: {
  children: ReactNode;
  isSearching: boolean;
  label: string;
  onQueryChange: (query: string) => void;
  onSearch: () => void;
  query: string;
}) {
  return (
    <div className="grid gap-2">
      <p className={textClasses.label}>{label}</p>
      <div className="flex gap-2">
        <input
          aria-label={label}
          className={`${controlClasses.controlRadius} min-w-0 flex-1 border border-ctp-surface1 bg-ctp-surface0 px-2.5 py-1.5 text-[12px] text-ctp-text outline-none focus:border-ctp-mauve`}
          placeholder="Search by title, artist, path, or id"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              onSearch();
            }
          }}
        />
        <ActionButton className={controlClasses.actionButtonCompact} disabled={isSearching} onClick={onSearch}>
          {isSearching ? "Searching..." : "Search"}
        </ActionButton>
      </div>
      {children ? <div className="grid gap-1.5">{children}</div> : null}
    </div>
  );
}

function SearchResultButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      className={`${surfaceClasses.insetPanel} grid min-w-0 gap-0.5 px-3 py-2 text-left text-[12px] text-ctp-text hover:bg-ctp-surface1`}
      type="button"
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function HistoryList({ attempts }: { attempts: LocalTrackDetail["failed_ingestion_attempts"] }) {
  return (
    <div className="grid gap-2">
      <p className={textClasses.label}>Failed ingestion history</p>
      {attempts.length > 0 ? (
        <ul className="grid gap-2">
          {attempts.map((attempt) => (
            <li className={`${surfaceClasses.insetPanel} px-3 py-2`} key={attempt.id}>
              <p className={`${textClasses.caption} font-medium text-ctp-text`}>{attempt.filename}</p>
              <p className={`${textClasses.finePrint} text-ctp-subtext0`}>{attempt.failure_reason}</p>
              <p className={`${textClasses.finePrint} text-ctp-subtext0`}>{formatTimestamp(attempt.failed_at)}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className={textClasses.caption}>No failed ingestion attempts.</p>
      )}
    </div>
  );
}

function Section({ children }: { children: ReactNode }) {
  return <section className="grid gap-3">{children}</section>;
}

function FieldGrid({ children }: { children: ReactNode }) {
  return <dl className="grid gap-2 sm:grid-cols-2">{children}</dl>;
}

function DetailField({
  copyValue,
  label,
  value,
  wide = false,
}: {
  copyValue?: string;
  label: string;
  value: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`grid min-w-0 gap-1 rounded-[8px] bg-ctp-surface0/48 px-2.5 py-2 ${wide ? "sm:col-span-2" : ""}`}>
      <dt className={`${textClasses.detail} text-ctp-subtext0`}>{label}</dt>
      <dd className="flex min-w-0 items-start justify-between gap-2">
        <span className={`${textClasses.caption} min-w-0 break-words text-ctp-text`}>{value}</span>
        {copyValue ? <CopyButton value={copyValue} /> : null}
      </dd>
    </div>
  );
}

function CopyButton({ value }: { value: string }) {
  return (
    <button
      aria-label="Copy value"
      className="shrink-0 text-ctp-subtext0 hover:text-ctp-text"
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value);
      }}
    >
      <Copy aria-hidden="true" className="h-3.5 w-3.5" />
    </button>
  );
}

function MutationStatus({ status }: { status: string | null }) {
  if (!status) {
    return null;
  }

  return <p className={`${textClasses.caption} font-medium text-ctp-subtext0`}>{status}</p>;
}

function getDrawerTitle(target: TrackDetailTarget | null, detail: unknown) {
  if (!target) {
    return "Track detail";
  }

  if (!detail) {
    return target.type === "local" ? `Local #${target.id}` : `Streaming #${target.id}`;
  }

  return target.type === "local"
    ? (detail as LocalTrackDetail).title ?? filename((detail as LocalTrackDetail).file_path)
    : (detail as StreamingTrackDetail).title;
}

function filename(path: string | null | undefined) {
  if (!path) {
    return "Unavailable";
  }

  return path.split("/").pop() || path;
}

function displayFilePath(track: { file_path: string | null | undefined; library_root_rel_path?: string | null }) {
  return track.library_root_rel_path || track.file_path || "Unavailable";
}

function localTrackAudioLabel(track: { file_path: string; title?: string | null }) {
  return `Listen to ${track.title ?? filename(track.file_path)}`;
}

function formatTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Unavailable";
  }

  return timestamp.replace("T", " ").replace(/(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/, "");
}

function formatResolutionSource(source: string) {
  if (source === "direct") {
    return "Direct link";
  }

  if (source === "equivalent") {
    return "Resolved through equivalent track";
  }

  return titleCase(source);
}

function formatSyncMode(syncMode: string) {
  if (syncMode === "full") {
    return "Full sync";
  }

  if (syncMode === "match_only") {
    return "Match-only sync";
  }

  if (syncMode === "off") {
    return "Sync off";
  }

  return titleCase(syncMode);
}

function titleCase(value: string) {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function truncateMiddle(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }

  const edgeLength = Math.max(8, Math.floor((maxLength - 3) / 2));
  return `${value.slice(0, edgeLength)}...${value.slice(value.length - edgeLength)}`;
}
