export type RescuedLocalTrack = {
  beets_id: number | null;
  file_path: string;
  fingerprint: string | null;
  id: number;
  library_root_rel_path: string | null;
};

export async function rescueLocalTrackMetadata(localTrackId: number | string): Promise<RescuedLocalTrack> {
  const response = await fetch(`/local-tracks/${encodeURIComponent(String(localTrackId))}/rescue`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Metadata rescue request failed with status ${response.status}`);
  }

  return (await response.json()) as RescuedLocalTrack;
}
