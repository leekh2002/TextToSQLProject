export type AuthUser = {
  id?: string
  studentNo: string
  name: string
  departmentCode?: string
  departmentName?: string
}

export type AuthResult = {
  user: AuthUser
  token?: string
}

export type AuthService = {
  getCurrentUser: () => Promise<AuthUser | null>
  login: (studentNo: string, password: string) => Promise<AuthUser>
  signup: (
    name: string,
    studentNo: string,
    password: string,
    departmentCode: string,
  ) => Promise<AuthUser>
  logout: () => Promise<void>
}
