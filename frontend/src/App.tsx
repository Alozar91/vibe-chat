/** Маршруты и auth-gate (§5): защищённая зона + /login, /register. */

import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from 'react-oidc-context'
import { configureAuthHooks } from '@/api/client'
import { useAuthHooks, setTokenGetter } from '@/auth/oidc'
import { ChatPage } from '@/pages/ChatPage'
import { LoginPage } from '@/pages/LoginPage'
import { RegisterPage } from '@/pages/RegisterPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { ChatsLayout } from '@/components/ChatsLayout'
import { connectWs, disconnectWs } from '@/realtime/ws'
import { WsEventsBridge } from '@/components/WsEventsBridge'

function AuthGate({ children }: { children: React.ReactNode }) {
  const auth = useAuth()
  const { get, renew } = useAuthHooks()
  const queryClient = useQueryClient()

  // токен → API-клиент (вне React)
  useEffect(() => {
    setTokenGetter(get)
    configureAuthHooks(get, renew)
  }, [get, renew])

  useEffect(() => {
    if (auth.isAuthenticated) {
      void connectWs()
      return () => disconnectWs()
    }
  }, [auth.isAuthenticated])

  if (auth.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted">Загрузка…</div>
    )
  }

  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return (
    <>
      <WsEventsBridge queryClient={queryClient} />
      {children}
    </>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        element={
          <AuthGate>
            <ChatsLayout />
          </AuthGate>
        }
      >
        <Route path="/" element={<ChatPage />} />
        <Route path="/chat/:chatId" element={<ChatPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
