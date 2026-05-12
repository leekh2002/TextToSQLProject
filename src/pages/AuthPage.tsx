import { useState } from 'react'
import type { FormEvent } from 'react'

type AuthPageProps = {
  onLogin: (studentNo: string, password: string) => Promise<string | null>
  onSignup: (
    name: string,
    studentNo: string,
    password: string,
    departmentCode: string,
  ) => Promise<string | null>
  onBack: () => void
}

type AuthMode = 'login' | 'signup'

export default function AuthPage({ onLogin, onSignup, onBack }: AuthPageProps) {
  const [mode, setMode] = useState<AuthMode>('login')
  const [name, setName] = useState('')
  const [studentNo, setStudentNo] = useState('')
  const [departmentCode, setDepartmentCode] = useState('CSE')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function resetFields() {
    setName('')
    setStudentNo('')
    setDepartmentCode('CSE')
    setPassword('')
    setConfirmPassword('')
    setError('')
  }

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode)
    resetFields()
  }

  function validateStudentNo(nextStudentNo: string) {
    // 학번은 보통 숫자만으로 구성되며, 자릿수는 학교/전산에 따라 다를 수 있어 8~12자리 범위로 완화합니다.
    return /^\d{8,12}$/.test(nextStudentNo)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')

    const trimmedStudentNo = studentNo.trim()

    if (!trimmedStudentNo || !password.trim()) {
      setError('학번과 비밀번호를 입력해주세요.')
      return
    }

    if (!validateStudentNo(trimmedStudentNo)) {
      setError('학번은 숫자만 입력하며 8~12자리여야 합니다.')
      return
    }

    setSubmitting(true)

    try {
      if (mode === 'signup') {
        if (!name.trim()) {
          setError('이름을 입력해주세요.')
          return
        }
        if (!departmentCode.trim()) {
          setError('학과를 선택해주세요.')
          return
        }
        if (password.length < 6) {
          setError('비밀번호는 6자 이상이어야 합니다.')
          return
        }
        if (password !== confirmPassword) {
          setError('비밀번호 확인이 일치하지 않습니다.')
          return
        }
        const signupError = await onSignup(
          name.trim(),
          trimmedStudentNo,
          password,
          departmentCode,
        )
        if (signupError) {
          setError(signupError)
        }
        return
      }

      const loginError = await onLogin(trimmedStudentNo, password)
      if (loginError) {
        setError(loginError)
      }
    } catch {
      setError('인증 처리 중 오류가 발생했습니다. 다시 시도해주세요.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-8">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <div className="text-lg font-bold text-slate-900">
              Course Registration
            </div>
            <div className="text-sm text-slate-500">충남대 통합정보 학번으로 로그인</div>
          </div>
          <button
            type="button"
            onClick={onBack}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
          >
            메인으로
          </button>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl bg-slate-100 p-1">
          <button
            type="button"
            onClick={() => switchMode('login')}
            className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
              mode === 'login'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            로그인
          </button>
          <button
            type="button"
            onClick={() => switchMode('signup')}
            className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
              mode === 'signup'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            회원가입
          </button>
        </div>

        <form className="space-y-3" onSubmit={handleSubmit}>
          {mode === 'signup' && (
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                이름
              </label>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={submitting}
                className="h-11 w-full rounded-xl border border-slate-200 px-3 text-sm text-slate-900 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
                placeholder="홍길동"
              />
            </div>
          )}

          <div>
            <label className="mb-1 block text-xs font-semibold text-slate-700">
              학번
            </label>
            <input
              type="text"
              value={studentNo}
              onChange={(event) => setStudentNo(event.target.value)}
              disabled={submitting}
              className="h-11 w-full rounded-xl border border-slate-200 px-3 text-sm text-slate-900 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
              placeholder="202012345"
            />
          </div>

          {mode === 'signup' && (
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                학과
              </label>
              <select
                value={departmentCode}
                onChange={(event) => setDepartmentCode(event.target.value)}
                disabled={submitting}
                className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
              >
                <option value="CSE">컴퓨터공학과</option>
                <option value="SWE">소프트웨어학과</option>
                <option value="AI">인공지능학과</option>
                <option value="EEE">전자공학과</option>
                <option value="MATH">수학과</option>
              </select>
            </div>
          )}

          <div>
            <label className="mb-1 block text-xs font-semibold text-slate-700">
              비밀번호
            </label>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={submitting}
              className="h-11 w-full rounded-xl border border-slate-200 px-3 text-sm text-slate-900 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
              placeholder="통합정보 비밀번호"
            />
          </div>

          {mode === 'signup' && (
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                비밀번호 확인
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                disabled={submitting}
                className="h-11 w-full rounded-xl border border-slate-200 px-3 text-sm text-slate-900 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
                placeholder="비밀번호 재입력"
              />
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 h-11 w-full rounded-xl bg-blue-600 text-sm font-semibold text-white transition hover:bg-blue-700"
          >
            {submitting
              ? '처리 중...'
              : mode === 'login'
                ? '로그인'
                : '회원가입'}
          </button>
        </form>
      </div>
    </div>
  )
}
