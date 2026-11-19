/** Страница входа (§5): выбор «Войти» (OIDC redirect на KC) / «Зарегистрироваться».
 *
 * Без автозапуска signinRedirect: мгновенный редирект на KC делал
 * регистрацию недостижимой (на KC-форме регистрации нет —
 * registrationAllowed: false). Callback (?code=…) обрабатывает AuthProvider
 * сам; по готовности сессии — сразу navigate('/') без промежуточных экранов.
 */

import { useEffect } from 'react'
import { useAuth } from 'react-oidc-context'
import { Link, useNavigate } from 'react-router-dom'
import { MessageSquare } from 'lucide-react'

export function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const isCallback = window.location.search.includes('code=')

  useEffect(() => {
    if (auth.isLoading) return
    if (auth.isAuthenticated) navigate('/', { replace: true })
  }, [auth, navigate])

  if (auth.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-muted">Загрузка…</div>
      </div>
    )
  }

  if (isCallback && !auth.isAuthenticated && !auth.error) {
    // AuthProvider завершает callback сам — ждём
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-muted">Вход…</div>
      </div>
    )
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-[360px] rounded-xl border border-border bg-panel p-8">
        <div className="mb-6 flex flex-col items-center gap-2">
          <MessageSquare className="size-10 text-accent" />
          <h1 className="text-lg font-semibold">Vibe Chat</h1>
        </div>
        {auth.error && (
          <div className="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">Ошибка входа: {auth.error.message}</div>
        )}
        <div className="flex flex-col gap-3">
          <button
            onClick={() => void auth.signinRedirect()}
            className="rounded-lg bg-accent py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Войти
          </button>
          <Link
            to="/register"
            className="rounded-lg border border-border py-2 text-center text-sm text-muted hover:border-accent hover:text-text"
          >
            Зарегистрироваться
          </Link>
        </div>
      </div>
    </div>
  )
}
