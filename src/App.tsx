import { useEffect, useState } from 'react'
import AuthPage from './pages/AuthPage'
import MainPage from './pages/MainPage'
import { authService } from './services/auth'
import type { AuthUser } from './types/auth'

export default function App() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)
  const [authPageOpen, setAuthPageOpen] = useState(false)

  useEffect(() => {
    let disposed = false

    async function loadCurrentUser() {
      const user = await authService.getCurrentUser()
      if (!disposed) {
        setCurrentUser(user)
      }
    }

    void loadCurrentUser()

    return () => {
      disposed = true
    }
  }, [])

  async function handleLogin(studentNo: string, password: string) {
    try {
      const user = await authService.login(studentNo, password)
      setCurrentUser(user)
      setAuthPageOpen(false)
      return null
    } catch (error) {
      if (error instanceof Error) {
        return error.message
      }
      return 'Login failed.'
    }
  }

  async function handleSignup(
    name: string,
    studentNo: string,
    password: string,
    departmentCode: string,
  ) {
    try {
      const user = await authService.signup(
        name,
        studentNo,
        password,
        departmentCode,
      )
      setCurrentUser(user)
      setAuthPageOpen(false)
      return null
    } catch (error) {
      if (error instanceof Error) {
        return error.message
      }
      return 'Sign up failed.'
    }
  }

  async function handleLogout() {
    await authService.logout()
    setCurrentUser(null)
  }

  if (authPageOpen) {
    return (
      <AuthPage
        onLogin={handleLogin}
        onSignup={handleSignup}
        onBack={() => setAuthPageOpen(false)}
      />
    )
  }

  return (
    <MainPage
      userName={currentUser?.name}
      onLoginClick={() => setAuthPageOpen(true)}
      onLogout={handleLogout}
    />
  )
}
