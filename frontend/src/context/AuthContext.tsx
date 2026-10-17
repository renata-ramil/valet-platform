import { createContext, useCallback, useContext, useEffect, useState } from "react"
import type { ReactNode } from "react"
import * as api from "../lib/apiClient"
import type { AuthUser } from "../lib/apiClient"

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (email: string, password: string) => Promise<{ mfaChallengeId: string | null }>
  verifyTotp: (challengeId: string, code: string) => Promise<void>
  register: (payload: {
    invite_code: string
    email: string
    password: string
    full_name: string
  }) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password)
    if (result.mfa_required) {
      return { mfaChallengeId: result.challenge_id }
    }
    setUser(result as AuthUser)
    return { mfaChallengeId: null }
  }, [])

  const verifyTotp = useCallback(async (challengeId: string, code: string) => {
    const loggedIn = await api.verifyTotp(challengeId, code)
    setUser(loggedIn)
  }, [])

  const register = useCallback(
    async (payload: {
      invite_code: string
      email: string
      password: string
      full_name: string
    }) => {
      await api.register(payload)
      await login(payload.email, payload.password)
    },
    [login],
  )

  const logout = useCallback(async () => {
    if (user) {
      await api.logout(user.csrf_token)
    }
    setUser(null)
  }, [user])

  return (
    <AuthContext.Provider value={{ user, loading, login, verifyTotp, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return context
}
