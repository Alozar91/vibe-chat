/**
 * Регистрация: POST /auth/register (§3.2) — инвайт-код ИЛИ открытый режим.
 * Персональные данные — только в PostgreSQL системы (§5 концепции).
 * После 201 — автовход ROPC теми же учётными данными.
 */

import { ApiError, api } from "./api-client";
import { login } from "./session-service";

export interface RegisterInput {
  username: string;
  password: string;
  inviteCode?: string;
  displayName?: string;
  firstName?: string;
  lastName?: string;
  email?: string;
}

interface RegisterResponse {
  id: string;
  username: string;
}

/** Открытый режим? 405/403 на /auth/register без кода — признак закрытой регистрации. */
export async function register(input: RegisterInput): Promise<RegisterResponse> {
  const body: Record<string, string> = {
    username: input.username,
    password: input.password,
  };
  if (input.inviteCode) body.invite_code = input.inviteCode;
  if (input.displayName) body.display_name = input.displayName;
  if (input.firstName) body.first_name = input.firstName;
  if (input.lastName) body.last_name = input.lastName;
  if (input.email) body.email = input.email;

  const created = await api<RegisterResponse>("/auth/register", { method: "POST", body });
  await login(input.username, input.password);
  return created;
}

/** Текст ошибки регистрации для UI. */
export function registerErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 422) return "Проверьте поля: username ≥ 3 символов, пароль ≥ 8";
    if (e.status === 409) return "Имя пользователя уже занято";
    if (e.status === 403 || e.status === 404) return "Регистрация закрыта: нужен инвайт-код";
    if (e.status === 0) return "Нет соединения";
    return e.message;
  }
  return "Неизвестная ошибка";
}
