export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type Dashboard = {
  stats: {
    total_users: number;
    total_topics: number;
    new_topics_today: number;
    active_topics: number;
    closed_topics: number;
    deleted_topics: number;
    restored_topics: number;
    total_messages: number;
    messages_today: number;
    total_media: number;
    media_today: number;
    channel_posts: number;
    gallery_posts: number;
    average_chat_length: number;
    average_days: number;
    retention_d7: number;
    top_users: { id: number; tg_id: number; name: string; username: string | null; messages: number; topics: number }[];
    top_active_hours: { hour: number; messages: number }[];
    top_media: { kind: string; count: number; bytes: number }[];
  };
  daily: { day: string; messages: number; topics: number }[];
  weekly: { week: string; messages: number; topics: number }[];
  monthly: { month: string; messages: number; topics: number }[];
};

export type Topic = {
  id: number;
  code: string;
  title: string;
  chat_id: number;
  message_thread_id: number | null;
  owner_id: number;
  partner_id: number | null;
  status: string;
  is_closed: boolean;
  message_count: number;
  media_count: number;
  restore_count: number;
  delete_at: string | null;
  created_at: string;
};

export type UserRow = {
  id: number;
  tg_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  gender: string;
  role: string;
  is_banned: boolean;
  is_muted: boolean;
  warns: number;
  messages_sent: number;
  topics_created: number;
  created_at: string;
};

/**
 * Operator-facing metadata for a setting, from `SETTINGS_META` on the backend.
 *
 * `enforcement` is the part that matters: it says whether the platform can
 * actually guarantee the toggle. `advisory` means the value is stored and shown
 * but *not* enforceable — `topic.copy_enabled` is the standing example, because
 * a silently copied message is indistinguishable from a typed one.
 */
export type Enforcement = "enforced" | "reactive" | "advisory";

export type SettingMeta = {
  label: string;
  enforcement: Enforcement;
  note: string;
};

export type AuditRow = {
  id: number;
  action: string;
  actor_tg_id: number | null;
  topic_id: number | null;
  ip: string | null;
  device: string | null;
  source: string;
  message: string | null;
  at: string | null;
};

export type MediaRow = {
  id: number;
  topic_code: string;
  kind: string;
  file_id: string;
  file_size: number;
  width: number | null;
  height: number | null;
  duration: number | null;
  mime_type: string | null;
  caption: string | null;
  published_to_channel: boolean;
  nsfw: boolean;
  nsfw_score: number;
  created_at: string | null;
};

export type EventRow = {
  id: number;
  topic_code: string;
  kind: string;
  title: string;
  description: string | null;
  due_at: string | null;
  remind_at: string | null;
  location: string | null;
  checklist: string[] | null;
  status: string;
  created_at: string | null;
};

export type ChannelPostRow = {
  id: number;
  topic_code: string | null;
  kind: string;
  tg_message_id: number | null;
  text: string | null;
  template: string | null;
  media_file_ids: string[] | null;
  published_at: string | null;
  failed_reason: string | null;
  created_at: string | null;
};

export type NotificationRow = {
  id: number;
  tg_id: number;
  username: string | null;
  kind: string;
  title: string | null;
  body: string;
  status: string;
  sent_at: string | null;
  error: string | null;
  created_at: string | null;
};

export type SubscriptionRow = {
  tg_id: number;
  username: string | null;
  first_name: string | null;
  kind: string;
  chat_id: number;
  is_member: boolean;
  status: string;
  checked_at: string | null;
};

export type BackupRow = {
  id: number;
  target: string;
  status: string;
  path: string | null;
  size: number;
  checksum: string | null;
  error: string | null;
  started_at: string | null;
};

const TOKEN_KEY = "soulchat.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    // Prefer FastAPI's `detail`; fall back to the HTTP reason phrase. Dumping a
    // raw `{}` into the UI (what `detail ?? JSON.stringify(body)` produced when
    // the body was an empty object) tells the operator nothing.
    let detail = response.statusText || `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body?.detail === "string" && body.detail) {
        detail = body.detail;
      } else if (body && typeof body === "object" && Object.keys(body).length > 0) {
        detail = JSON.stringify(body);
      }
    } catch {
      /* non json error body — keep the reason phrase */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const endpoints = {
  login: (body: { username: string; password: string }) =>
    api<TokenPair>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => api<{ id: number; username: string; role: string; name: string }>("/api/v1/auth/me"),
  dashboard: (days = 30) => api<Dashboard>(`/api/v1/analytics/dashboard?days=${days}`),
  topics: (status?: string) =>
    api<{ items: Topic[]; total: number }>(
      `/api/v1/topics${status ? `?status=${encodeURIComponent(status)}` : ""}`
    ),
  topicAction: (code: string, action: string, reason = "") =>
    api<Topic>(`/api/v1/topics/${code}/${action}`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  users: () => api<UserRow[]>("/api/v1/users?limit=200"),
  audit: () => api<AuditRow[]>("/api/v1/moderation/audit?limit=100"),
  settings: () =>
    api<{ items: Record<string, unknown>; meta?: Record<string, SettingMeta> }>("/api/v1/settings"),
  updateSetting: (key: string, value: unknown) =>
    api<{ key: string; value: unknown }>("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ key, value }),
    }),
  backup: () =>
    api<{ status: string; path: string | null; size: number; error: string | null }>("/api/v1/backup", {
      method: "POST",
    }),
  backupHistory: () => api<BackupRow[]>("/api/v1/backup"),
  media: (params: { kind?: string; topic_code?: string } = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][]
    ).toString();
    return api<{ total: number; items: MediaRow[] }>(`/api/v1/media${query ? `?${query}` : ""}`);
  },
  events: (params: { status?: string; topic_code?: string } = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][]
    ).toString();
    return api<{ total: number; items: EventRow[] }>(`/api/v1/events${query ? `?${query}` : ""}`);
  },
  channelPosts: (kind?: string) =>
    api<{ total: number; items: ChannelPostRow[] }>(
      `/api/v1/channel-posts${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`
    ),
  notifications: (status?: string) =>
    api<{ total: number; items: NotificationRow[] }>(
      `/api/v1/notifications${status ? `?status=${encodeURIComponent(status)}` : ""}`
    ),
  moderate: (body: { tg_id: number; action: string; reason?: string }) =>
    api<{ user_id: number; warns: number }>("/api/v1/moderation/action", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  backupVerify: (id: number) =>
    api<{ id: number; status: string; expected: string | null; actual: string | null }>(
      "/api/v1/backup/verify",
      { method: "POST", body: JSON.stringify({ id }) }
    ),
  backupFileUrl: (id: number) => `/api/v1/backup/${id}/file`,
  exportUrl: (entity: "users" | "topics" | "messages", fmt: "csv" | "json" = "csv") =>
    `/api/v1/export/${entity}?fmt=${fmt}`,
  subscriptions: (isMember?: boolean) =>
    api<{ total: number; items: SubscriptionRow[] }>(
      `/api/v1/subscriptions${isMember === undefined ? "" : `?is_member=${isMember}`}`
    ),
  search: (query: string) =>
    api<Record<string, unknown[]>>("/api/v1/analytics/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
};