/** Тонкий fetch-клиент /api/v1: Bearer из OIDC, 401 → silent renew → retry (§5). */

import type { Chat, ChatDetails, ChatMember, FileOut, Invite, InviteCreated, Message, User } from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type TokenGetter = () => string | undefined
type Renewer = () => Promise<void>

let getToken: TokenGetter = () => undefined
let renew: Renewer = async () => {}

/** Инициализация клиентскими провайдерами auth (main.tsx). */
export function configureAuthHooks(get: TokenGetter, renewFn: Renewer): void {
  getToken = get
  renew = renewFn
}

const BASE = '/api/v1'

async function request<T>(
  method: string,
  path: string,
  options: {
    json?: unknown
    query?: Record<string, string | number | undefined>
    headers?: Record<string, string>
    retried?: boolean
  } = {},
): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  for (const [k, v] of Object.entries(options.query ?? {})) {
    if (v !== undefined) url.searchParams.set(k, String(v))
  }

  const headers: Record<string, string> = { ...(options.headers ?? {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.json !== undefined) headers['Content-Type'] = 'application/json'

  const resp = await fetch(url.pathname + url.search, {
    method,
    headers,
    body: options.json !== undefined ? JSON.stringify(options.json) : undefined,
  })

  // протухший токен: тихо обновляем и повторяем один раз (§5 silent refresh)
  if (resp.status === 401 && !options.retried) {
    try {
      await renew()
      return await request<T>(method, path, { ...options, retried: true })
    } catch {
      throw new ApiError(401, 'unauthorized')
    }
  }

  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = (await resp.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // не JSON — оставляем statusText
    }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export const api = {
  get: <T>(path: string, query?: Record<string, string | number | undefined>) =>
    request<T>('GET', path, { query }),
  post: <T>(path: string, json?: unknown, headers?: Record<string, string>) =>
    request<T>('POST', path, { json, headers }),
  put: <T>(path: string, json?: unknown) => request<T>('PUT', path, { json }),
  patch: <T>(path: string, json: unknown) => request<T>('PATCH', path, { json }),
  delete: <T>(path: string, json?: unknown) => request<T>('DELETE', path, { json }),
}

// --- Users ---

export const usersApi = {
  me: () => api.get<User>('/users/me'),
  updateMe: (patch: Partial<Pick<User, 'display_name' | 'first_name' | 'last_name' | 'email' | 'avatar_file_id' | 'time_display' | 'timezone'>>) =>
    api.patch<User>('/users/me', patch),
  search: (q: string) => api.get<User[]>('/users', { q }),
  get: (id: string) => api.get<User>(`/users/${id}`),
}

// --- Auth (регистрация по инвайту, без токена) ---

export interface RegisterPayload {
  invite_code: string
  username: string
  password: string
  first_name?: string
  last_name?: string
  email?: string
  display_name?: string
}

export function registerWithInvite(payload: RegisterPayload): Promise<User> {
  // публичный эндпоинт — без Authorization
  return request<User>('POST', '/auth/register', { json: payload })
}

// --- Chats ---

export const chatsApi = {
  list: () => api.get<Chat[]>('/chats'),
  get: (id: string) => api.get<ChatDetails>(`/chats/${id}`),
  createGroup: (title: string, memberIds: string[]) =>
    api.post<Chat>('/chats', { title, member_ids: memberIds }),
  // бэкенд отвечает {chat_id, created} (§12) — не Chat
  createDirect: (userId: string) => api.post<{ chat_id: string; created: boolean }>('/chats/direct', { user_id: userId }),
  rename: (id: string, title: string) => api.patch<Chat>(`/chats/${id}`, { title }),
  setMemberRole: (id: string, userId: string, role: 'admin' | 'member') =>
    api.patch<ChatMember>(`/chats/${id}/members/${userId}`, { role }),
  transferOwnership: (id: string, userId: string) => api.post<void>(`/chats/${id}/owner`, { user_id: userId }),
  delete: (id: string) => api.delete<void>(`/chats/${id}`),
  addMembers: (id: string, memberIds: string[]) =>
    api.post<void>(`/chats/${id}/members`, { member_ids: memberIds }),
  removeMember: (id: string, userId: string) =>
    api.delete<void>(`/chats/${id}/members/${userId}`),
  read: (id: string, messageId: string) => api.post<void>(`/chats/${id}/read`, { message_id: messageId }),
}

// --- Files (upload-флоу §8: upload-url → presigned PUT → complete) ---

export const filesApi = {
  /** Presigned PUT + file_id (pending). sha256 — hex, считается клиентом (WebCrypto). */
  uploadUrl: (size: number, mime: string, sha256: string) =>
    api.post<{ file_id: string; upload_url: string; expires_in: number }>('/files/upload-url', {
      size,
      mime,
      sha256,
    }),
  complete: (fileId: string) => api.post<FileOut>(`/files/${fileId}/complete`),
  url: (fileId: string) => api.get<{ url: string; expires_in: number }>(`/files/${fileId}/url`),
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/** Полный upload-флоу §8: upload-url → PUT в Silo → complete → ready file_id. */
export async function uploadFile(file: File): Promise<{ file_id: string; mime: string }> {
  const buf = await file.arrayBuffer()
  const sha256 = await sha256Hex(buf)
  // браузер не всегда определяет mime (зависит от ОС) — бэкенд всё равно
  // переопределяет его sniffing'ом при complete (§8, mime из клиента не доверенный)
  const mime = file.type || 'application/octet-stream'
  const { file_id, upload_url } = await filesApi.uploadUrl(file.size, mime, sha256)
  const res = await fetch(upload_url, {
    method: 'PUT',
    body: buf,
    headers: { 'Content-Type': mime },
  })
  if (!res.ok) throw new ApiError(res.status, `Silo upload failed: ${res.status}`)
  await filesApi.complete(file_id)
  return { file_id, mime }
}

// --- Messages ---

export const messagesApi = {
  list: (chatId: string, query: { before?: string; after?: string; updated_after?: string; limit?: number }) =>
    api.get<Message[]>(`/chats/${chatId}/messages`, query),
  send: (
    chatId: string,
    payload: {
      text?: string
      attachments?: { file_id: string; kind: 'image' | 'video' | 'file'; file_name: string }[]
      reply_to_id?: string
      client_ref?: string
      timezone?: string
    },
    idempotencyKey?: string,
  ) =>
    api.post<Message>(`/chats/${chatId}/messages`, payload, idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined),
  edit: (id: string, text: string) => api.patch<Message>(`/messages/${id}`, { text }),
  delete: (id: string) => api.delete<Message>(`/messages/${id}`),
  forward: (id: string, chatIds: string[]) => api.post<Message[]>(`/messages/${id}/forward`, { chat_ids: chatIds }),
  react: (id: string, emoji: string) => api.put<Message['reactions']>(`/messages/${id}/reactions`, { emoji }),
}

// --- Invites (платформенный админ) ---

export const invitesApi = {
  list: () => api.get<Invite[]>('/invites'),
  create: (maxUses?: number, expiresAt?: string) =>
    api.post<InviteCreated>('/invites', { max_uses: maxUses, expires_at: expiresAt }),
  deactivate: (id: string) => api.post<Invite>(`/invites/${id}/deactivate`),
}
