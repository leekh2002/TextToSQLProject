import { apiClient } from '../apiClient'
import type { GraduationStatusResponse, UserProfile } from '../../types/api'

export function getMyProfile() {
  return apiClient.get<UserProfile>('/students/me/profile')
}

export function getGraduationStatus() {
  return apiClient.get<GraduationStatusResponse>('/students/me/graduation-status')
}

export function syncStudentData() {
  return apiClient.post<{ requested: boolean; syncedAt?: string }>('/students/me/sync')
}
