import type { AuthService } from '../../types/auth'
import { localAuthService } from './localAuthService'
import { remoteAuthService } from './remoteAuthService'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

export const authService: AuthService =
  apiBaseUrl && apiBaseUrl.length > 0
    ? remoteAuthService
    : localAuthService
