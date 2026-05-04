import { Folder, Plus, Trash2 } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage, type OperationStatus } from "../../components/StatusMessage";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  type IngestFolder,
  useCreateIngestFolderMutation,
  useDeleteIngestFolderMutation,
  useGeneralSettingsQuery,
} from "./queries";

type IngestFolderMutationMessage = {
  body: string;
  status: OperationStatus;
  title: string;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function IngestFolderRow({
  folder,
  isDeleting,
  onDelete,
}: {
  folder: IngestFolder;
  isDeleting: boolean;
  onDelete: (folderId: number) => void;
}) {
  return (
    <article className={surfaceClasses.rowCardCompact}>
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className={`${controlClasses.iconFrame} h-9 w-9 shrink-0`} aria-hidden="true">
            <Folder className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className={`truncate font-mono ${textClasses.title}`}>{folder.path}</h3>
            <p className={`mt-1 ${textClasses.caption}`}>Folder ID {folder.id}</p>
          </div>
        </div>
        <button
          aria-label={`Remove ingest folder ${folder.path}`}
          className={`${controlClasses.controlRadius} flex h-9 w-9 shrink-0 items-center justify-center border border-ctp-red/35 bg-ctp-red/10 text-ctp-red transition-colors hover:bg-ctp-red/18 disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:bg-ctp-surface0 disabled:text-ctp-overlay1`}
          disabled={isDeleting}
          onClick={() => onDelete(folder.id)}
          title={`Remove ${folder.path}`}
          type="button"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </article>
  );
}

function IngestFolderState({ status }: { status: "empty" | "error" | "loading" }) {
  const copy = {
    empty: {
      title: "No ingest folders",
      body: "Add an absolute container path to start watching it for new music files.",
      tone: "neutral",
    },
    error: {
      title: "General settings unavailable",
      body: "Ingest folders could not be loaded. Try again after the backend database is reachable.",
      tone: "error",
    },
    loading: {
      title: "Loading general settings",
      body: "Checking configured ingest folders.",
      tone: "neutral",
    },
  } as const;
  const state = copy[status];

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center">
      <EmptyStateCard
        body={state.body}
        className={layoutClasses.emptyStateNarrow}
        role={status === "loading" ? "status" : status === "error" ? "alert" : undefined}
        title={state.title}
        tone={state.tone}
      />
    </div>
  );
}

export function GeneralSettingsView() {
  const [folderPath, setFolderPath] = useState("");
  const generalSettingsQuery = useGeneralSettingsQuery();
  const createFolderMutation = useCreateIngestFolderMutation();
  const deleteFolderMutation = useDeleteIngestFolderMutation();
  const folders = generalSettingsQuery.data?.ingest_folders ?? [];
  const trimmedFolderPath = folderPath.trim();
  const mutationMessage = useMemo<IngestFolderMutationMessage | null>(() => {
    if (createFolderMutation.isPending) {
      return {
        body: `Adding ${trimmedFolderPath || "ingest folder"} to the active watcher.`,
        status: "pending",
        title: "Adding ingest folder",
      };
    }

    if (deleteFolderMutation.isPending) {
      return {
        body: "Removing this folder from the active watcher.",
        status: "pending",
        title: "Removing ingest folder",
      };
    }

    if (createFolderMutation.isError) {
      return {
        body: getErrorMessage(createFolderMutation.error, "The ingest folder could not be added."),
        status: "error",
        title: "Add failed",
      };
    }

    if (deleteFolderMutation.isError) {
      return {
        body: getErrorMessage(deleteFolderMutation.error, "The ingest folder could not be removed."),
        status: "error",
        title: "Remove failed",
      };
    }

    if (createFolderMutation.isSuccess) {
      return {
        body: "The folder was saved and added to the active watcher.",
        status: "success",
        title: "Ingest folder added",
      };
    }

    if (deleteFolderMutation.isSuccess) {
      return {
        body: "The folder was removed from the active watcher.",
        status: "success",
        title: "Ingest folder removed",
      };
    }

    return null;
  }, [
    createFolderMutation.error,
    createFolderMutation.isError,
    createFolderMutation.isPending,
    createFolderMutation.isSuccess,
    deleteFolderMutation.error,
    deleteFolderMutation.isError,
    deleteFolderMutation.isPending,
    deleteFolderMutation.isSuccess,
    trimmedFolderPath,
  ]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!trimmedFolderPath || createFolderMutation.isPending) {
      return;
    }

    createFolderMutation.mutate(
      { path: trimmedFolderPath },
      {
        onSuccess: () => setFolderPath(""),
      },
    );
  }

  function handleDelete(folderId: number) {
    if (deleteFolderMutation.isPending) {
      return;
    }

    deleteFolderMutation.mutate(folderId);
  }

  if (generalSettingsQuery.isPending) {
    return <IngestFolderState status="loading" />;
  }

  if (generalSettingsQuery.isError) {
    return <IngestFolderState status="error" />;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>General settings</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {folders.length} ingest {folders.length === 1 ? "folder" : "folders"} configured.
          </p>
        </div>
        <form className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-[24rem]" onSubmit={handleSubmit}>
          <label className={textClasses.label} htmlFor="new-ingest-folder-path">
            Add ingest folder
          </label>
          <div className={`${controlClasses.searchFrame} flex min-h-10 items-center gap-2 px-2.5`}>
            <Plus className="h-4 w-4 shrink-0 text-ctp-mauve" aria-hidden="true" />
            <input
              className={`min-w-0 flex-1 bg-transparent py-2 text-ctp-text outline-none placeholder:text-ctp-overlay1 ${textClasses.input}`}
              disabled={createFolderMutation.isPending}
              id="new-ingest-folder-path"
              onChange={(event) => setFolderPath(event.target.value)}
              placeholder="/soulseek"
              type="text"
              value={folderPath}
            />
            <ActionButton disabled={!trimmedFolderPath || createFolderMutation.isPending} type="submit">
              {createFolderMutation.isPending ? "Adding..." : "Add"}
            </ActionButton>
          </div>
        </form>
      </div>

      <div aria-label="Ingest folders" className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" role="region">
        <div className="space-y-3">
          {mutationMessage ? (
            <StatusMessage body={mutationMessage.body} status={mutationMessage.status} title={mutationMessage.title} />
          ) : null}
          {folders.length > 0 ? (
            folders.map((folder) => (
              <IngestFolderRow
                folder={folder}
                isDeleting={deleteFolderMutation.isPending && deleteFolderMutation.variables === folder.id}
                key={folder.id}
                onDelete={handleDelete}
              />
            ))
          ) : (
            <IngestFolderState status="empty" />
          )}
        </div>
      </div>
    </section>
  );
}
