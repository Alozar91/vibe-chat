/** OIDC auth (§5): Authorization Code + PKCE через oidc-client-ts. */

import { useCallback } from 'react'
import { useAuth } from 'react-oidc-context'
import { WebStorageStateStore } from 'oidc-client-ts'
import type { AuthContextProps } from 'react-oidc-context'

const KC_URL = import.meta.env.VITE_KC_URL ?? 'http://localhost:8080'
const REALM = import.meta.env.VITE_KC_REALM ?? 'vibe-chat'
const CLIENT_ID = import.meta.env.VITE_KC_CLIENT_ID ?? 'frontend'

export const oidcConfig = {
  authority: `${KC_URL}/realms/${REALM}`,
  client_id: CLIENT_ID,
  redirect_uri: window.location.origin + '/login',
  post_logout_redirect_uri: window.location.origin,
  response_type: 'code',
  scope: 'openid profile email',
  automaticSilentRenew: true,
  userStore: new WebStorageStateStore({ store: sessionStorage }),
}

export type { AuthContextProps }

/** Токен для API-клиента вне React: прокидывается из AuthGate через setTokenGetter. */
let tokenGetter: () => string | undefined = () => undefined

export function setTokenGetter(get: () => string | undefined): void {
  tokenGetter = get
}

export function getAccessToken(): string | undefined {
  return tokenGetter()
}

/** Хуки для configureAuthHooks (api/client.ts) — вызываются внутри AuthProvider. */
export function useAuthHooks() {
  const auth = useAuth()
  const get = useCallback(() => auth.user?.access_token, [auth.user])
  const renew = useCallback(async () => {
    await auth.signinSilent()
  }, [auth])
  return { get, renew }
}
