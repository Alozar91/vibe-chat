/** Страница логина: запускает OIDC redirect (§5). */

import { useEffect } from 'react'
import { useAuth } from 'react-oidc-context'
import { Link } from 'react-router-dom'
import { MessageSquare } from 'lucide-react'

export function LoginPage() {
  const auth = useAuth()

  useEffect(() => {
    // Пришли с редиректом KC — завершаем; иначе сразу редирект на логин
    if (!auth.isAuthenticated && !auth.isLoading && !window.location.search.includes('code=')) {
      void auth.signinRedirect()
    }
  }, [auth])

  if (auth.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-muted">Загрузка…</div>
      </div>
    )
  }

  if (auth.isAuthenticated) {
    return (
      <div className="flex h-full items-center justify-center">
        <Link to="/" className="text-accent hover:underline">
          Войти в мессенджер
        </Link>
      </div>
    )
  }

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
        Есть инвайт-код? Зарегистрироваться
      </Link>
    </div>
  )
}
