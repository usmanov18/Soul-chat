/** Small display helpers shared by the panel views. */

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value >= 100 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

export const MEDIA_KIND_ICONS: Record<string, string> = {
  photo: "📷",
  video: "🎬",
  voice: "🎙️",
  document: "📄",
  sticker: "🎭",
  animation: "🌀",
  audio: "🎵",
  video_note: "📹",
};

export function mediaKindIcon(kind: string): string {
  return MEDIA_KIND_ICONS[kind] ?? "📎";
}

export const EVENT_KIND_ICONS: Record<string, string> = {
  date: "📅",
  reminder: "⏰",
  photo: "📷",
  video: "🎬",
  location: "📍",
  checklist: "☑️",
  deadline: "⏳",
};

export function eventKindIcon(kind: string): string {
  return EVENT_KIND_ICONS[kind] ?? "📌";
}
