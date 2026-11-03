// Тонкий клиент API. Типы повторяют docs/03-design/openapi.yaml.

export type Marketplace = "wildberries" | "ozon" | "yandex_market";
export type ChatStatus = "new" | "in_progress" | "answered";

export interface Operator {
  id: number;
  login: string;
  display_name: string;
}

export interface ChatListItem {
  id: number;
  marketplace: Marketplace;
  buyer_name: string | null;
  product_title: string | null;
  order_number: string | null;
  status: ChatStatus;
  last_message_at: string;
  last_message_preview: string;
}

export interface Message {
  id: number;
  author: "buyer" | "operator";
  text: string;
  created_at: string;
}

export interface Chat extends Omit<ChatListItem, "last_message_preview"> {
  external_id: string;
  product_sku: string | null;
  draft_text: string | null;
  draft_note: string | null;
  messages: Message[];
}

export interface Feedback {
  id: number;
  marketplace: Marketplace;
  kind: "review" | "question";
  product_title: string | null;
  buyer_name: string | null;
  rating: number | null;
  text: string;
  created_at: string;
  answer_text: string | null;
  answered_at: string | null;
  draft_text: string | null;
  draft_note: string | null;
}

export interface Template {
  id: number;
  name: string;
  body: string;
  variables: string[];
}

export interface Draft {
  text: string;
  provider: string;
  note: string;
}

export interface TemplateReply {
  sent: boolean;
  text: string;
  missing: string[];
  note: string | null;
}

export interface SyncJob {
  id: number;
  status: "queued" | "running" | "done" | "failed";
  created_at: string;
  finished_at: string | null;
  chats_upserted: number;
  messages_inserted: number;
  feedback_upserted: number;
  error: string | null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "sellerdesk.token";

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // хранилище недоступно — вход живёт до перезагрузки
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // тело не JSON
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

const post = (body?: unknown, headers?: Record<string, string>): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
  headers,
});

export const PAGE = 100;

export const api = {
  login: (login: string, password: string) =>
    request<{ access_token: string; operator: Operator }>(
      "/api/auth/login",
      post({ login, password }),
    ),
  me: () => request<Operator>("/api/auth/me"),
  chats: (f: { marketplace?: string; status?: string; offset?: number }) =>
    request<{ items: ChatListItem[]; total: number }>(`/api/chats${qs({ limit: PAGE, ...f })}`),
  chat: (id: number) => request<Chat>(`/api/chats/${id}`),
  reply: (id: number, text: string, idempotencyKey: string) =>
    request<{ message: Message; duplicate: boolean }>(
      `/api/chats/${id}/reply`,
      post({ text }, { "Idempotency-Key": idempotencyKey }),
    ),
  chatDraft: (id: number) => request<Draft>(`/api/chats/${id}/ai-draft`, post()),
  chatTemplate: (id: number, templateId: number, idempotencyKey: string) =>
    request<TemplateReply>(
      `/api/chats/${id}/template-reply`,
      post({ template_id: templateId }, { "Idempotency-Key": idempotencyKey }),
    ),
  feedback: (f: {
    kind?: string;
    rating?: string;
    answered?: string;
    marketplace?: string;
    offset?: number;
  }) => request<{ items: Feedback[]; total: number }>(`/api/feedback${qs({ limit: PAGE, ...f })}`),
  answerFeedback: (id: number, text: string) =>
    request<Feedback>(`/api/feedback/${id}/answer`, post({ text })),
  feedbackDraft: (id: number) => request<Draft>(`/api/feedback/${id}/ai-draft`, post()),
  feedbackTemplate: (id: number, templateId: number) =>
    request<TemplateReply>(`/api/feedback/${id}/template-reply`, post({ template_id: templateId })),
  templates: () => request<Template[]>("/api/templates"),
  createTemplate: (name: string, body: string) =>
    request<Template>("/api/templates", post({ name, body })),
  startSync: () => request<SyncJob>("/api/sync", post()),
  sync: (id: number) => request<SyncJob>(`/api/sync/${id}`),
  latestSync: () => request<SyncJob | null>("/api/sync/latest"),
};

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
