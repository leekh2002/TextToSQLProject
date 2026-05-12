import * as authApi from '../api/authApi'
import type { AuthService, AuthUser } from '../../types/auth'

function toAuthUser(user: {
  id: string
  name: string
  studentNo: string
  departmentCode?: string
  departmentName?: string
}): AuthUser {
  return {
    id: user.id,
    name: user.name,
    studentNo: user.studentNo,
    departmentCode: user.departmentCode,
    departmentName: user.departmentName,
  }
}

export const remoteAuthService: AuthService = {
  async getCurrentUser() {
    try {
      const user = await authApi.getMe()
      return toAuthUser(user)
    } catch {
      return null
    }
  },

  async login(studentNo, password) {
    const result = await authApi.login({
      studentNo,
      password,
    })
    return toAuthUser(result.user)
  },

  async signup(name, studentNo, password, departmentCode) {
    const result = await authApi.signup({
      studentNo,
      name,
      password,
      departmentCode,
    })
    return toAuthUser(result.user)
  },

  async logout() {
    await authApi.logout()
  },
}
