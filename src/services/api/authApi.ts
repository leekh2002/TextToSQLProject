import { apiClient, clearAccessToken, setAccessToken } from '../apiClient'
import type {
  LoginRequest,
  LoginResponse,
  RefreshResponse,
  SignupRequest,
  UserProfile,
} from '../../types/api'

export async function login(payload: LoginRequest) {
  const result = await apiClient.post<LoginResponse>('/auth/login', payload, false)
  setAccessToken(result.accessToken)
  return result
}

export async function signup(payload: SignupRequest) {
  const result = await apiClient.post<LoginResponse>('/auth/signup', payload, false)
  setAccessToken(result.accessToken)
  return result
}

export async function refresh(refreshToken: string) {
  const result = await apiClient.post<RefreshResponse>(
    '/auth/refresh',
    { refreshToken },
    false,
  )
  setAccessToken(result.accessToken)
  return result
}

export async function logout() {
  try {
    await apiClient.post<void>('/auth/logout')
  } finally {
    clearAccessToken()
  }
}

export async function getMe() {
  const result = await apiClient.get<{ user: UserProfile }>('/students/me')
  return result.user
}
