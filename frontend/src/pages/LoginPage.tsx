/** Страница логина: redirect на KC (§5) и авто-переход в приложение после входа.
 *
 * Callback (?code=…) обрабатывает AuthProvider (react-oidc-context, авто-режим);
 * здесь только ждём его и по готовности сразу navigate('/', replace) —
 * без промежуточных кнопок («Войти в мессенджер» убрано, 2026-11-19).
 */

import { useEffect } from 'react'
import { useAuth } from 'react-oidc-context'
import { Link, useNavigate } from 'react-router-dom'
import { MessageSquare } from 'lucide-react'

export function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  // callback в URL живёт до завершения обработки (oidc-client-ts чистит историю сам)
  const isCallback = window.location.search.includes('code=')

  useEffect(() => {
    if (auth.isLoading) return
    if (auth.isAuthenticated) {
      navigate('/', { replace: true })
      return
    }
    if (isCallback || auth.error) return // AuthProvider завершает callback сам; при ошибке не зацикливаемся
    void auth.signinRedirect()
  }, [auth, isCallback, navigate])

  if (auth.isLoading || (isCallback && !auth.isAuthenticated)) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-muted">Вход…</div>
      </div>
    )
  }

  if (auth.error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <MessageSquare className="size-12 text-accent" />
        <div className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">Ошибка входа: {auth.error.message}</div>
        <button
          onClick={() => void auth.signinRedirect()}
          className="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          Повторить
        </button>
        <Link to="/register" className="text-sm text-muted hover:text-text">
          Нет аккаунта? Зарегистрироваться
        </Link>
      </div>
    )
  }

  // не-authenticated без callback (signinRedirect уже запущен эффектом) — страховка
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <MessageSquare className="size-12 text-accent" />
      <div className="text-lg">Перенаправление на страницу входа…</div>
      <button
        onClick={() => void auth.signinRedirect()}
        className="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-white hover:bg-accent-hover"
      >
        Войти
      </button>
      <Link to="/register" className="text-sm text-muted hover:text-text">
        Нет аккаунта? Зарегистрироваться
      </Link>
    </div>
  )
}
