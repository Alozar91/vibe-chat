/** Регистрация (§5): credentials → Keycloak, персональные данные → система.
 *
 * Инвайт-код опционален (открытая регистрация — APP_OPEN_REGISTRATION на
 * сервере). После успеха — автовход direct grant'ом (одна форма — один ввод
 * данных, §5); не удался — fallback: ссылка на обычный вход.
 */

import { useMutation } from '@tanstack/react-query'
import { MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { registerWithInvite } from '@/api/client'
import { signinResourceOwner } from '@/auth/oidc'

export function RegisterPage() {
  // код из инвайт-ссылки /register?code=… (§5); без ссылки поле пустое и необязательное
  const [params] = useSearchParams()
  const urlCode = params.get('code') ?? ''
  const [inviteCode, setInviteCode] = useState(urlCode)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [autoLoginFailed, setAutoLoginFailed] = useState(false)

  const register = useMutation({
    mutationFn: () =>
      registerWithInvite({
        invite_code: inviteCode.trim() || undefined,
        username: username.trim(),
        password,
        first_name: firstName.trim() || undefined,
        last_name: lastName.trim() || undefined,
        email: email.trim() || undefined,
        display_name: displayName.trim() || undefined,
      }),
    // автовход: ROPC с только что введёнными credentials (пароль уходит только в KC).
    // Полная перезагрузка, а не navigate(): AuthProvider видит пользователя только
    // при инициализации — SPA-переход попадал в AuthGate без сессии и выкидывал
    // на /login (набл. 2026-11-19)
    onSuccess: async () => {
      if (await signinResourceOwner(username.trim(), password)) {
        const base = import.meta.env.BASE_URL.replace(/\/$/, '')
        window.location.assign(base + '/')
      } else {
        setAutoLoginFailed(true) // fallback: обычный вход через Keycloak
      }
    },
  })

  const errorText = (): string => {
    const e = register.error as { status?: number; message?: string } | null
    if (!e) return ''
    switch (e.status) {
      case 404:
        return 'Инвайт-код не найден'
      case 410:
        return 'Код больше не действует (истёк, исчерпан или отключён)'
      case 409:
        return 'Имя пользователя уже занято'
      case 422:
        return 'Регистрация без инвайт-кода закрыта на этом сервере'
      case 502:
        return 'Сервис аутентификации недоступен, попробуйте позже'
      case 503:
        return 'Регистрация не настроена на сервере'
      default:
        return e.message ?? 'Ошибка регистрации'
    }
  }

  const inputCls =
    'w-full rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent'

  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-[400px] rounded-xl border border-border bg-panel p-6">
        <div className="mb-4 flex items-center gap-2">
          <MessageSquare className="size-6 text-accent" />
          <h1 className="text-lg font-semibold">Регистрация в Vibe Chat</h1>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            register.mutate()
          }}
          className="flex flex-col gap-3"
        >
          {urlCode ? (
            <div className="rounded-lg bg-panel-2 px-3 py-2 text-xs text-muted">
              Регистрация по инвайт-ссылке
            </div>
          ) : (
            <input
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              placeholder="Инвайт-код (vh_…) — если есть"
              className={inputCls}
            />
          )}
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Имя пользователя (латиница, ≥3 символов)"
            required
            minLength={3}
            pattern="[A-Za-z0-9_\-]+"
            className={inputCls}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль (минимум 8 символов)"
            required
            minLength={8}
            className={inputCls}
          />

          <div className="grid grid-cols-2 gap-2">
            <input
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="Имя"
              className={inputCls}
            />
            <input
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="Фамилия"
              className={inputCls}
            />
          </div>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email (необязательно)"
            className={inputCls}
          />
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Отображаемое имя (по умолчанию — логин)"
            className={inputCls}
          />

          <div className="text-xs text-muted">
            Имя, фамилия и email хранятся в системе (не в Keycloak) и доступны для редактирования
            в настройках профиля.
          </div>

          {register.isError && <div className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{errorText()}</div>}
          {register.isSuccess && !autoLoginFailed && (
            <div className="rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">Аккаунт создан, входим…</div>
          )}
          {register.isSuccess && autoLoginFailed && (
            <div className="rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">
              Аккаунт создан!{' '}
              <Link to="/login" className="underline">
                Войдите
              </Link>{' '}
              под своими логином и паролем.
            </div>
          )}

          <button
            type="submit"
            disabled={register.isPending}
            className="rounded-lg bg-accent py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-40"
          >
            {register.isPending ? 'Создание аккаунта…' : 'Зарегистрироваться'}
          </button>
          <Link to="/login" className="text-center text-sm text-muted hover:text-text">
            Уже есть аккаунт? Войти
          </Link>
        </form>
      </div>
    </div>
  )
}
