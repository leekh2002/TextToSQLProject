import { useEffect, useMemo, useRef, useState } from 'react'
import type { Course } from '../types/course'
import { cn } from '../utils/cn'
import Timetable from './Timetable'

type ChatMessage = {
  id: string
  role: 'user' | 'system'
  text: string
}

type QueryApiResponse = {
  sql?: string
  data?: unknown[]
  warning?: string
  error?: string
}

type QueryRow = Record<string, unknown>

function makeId(prefix: string) {
  return `${prefix}_${Math.random().toString(16).slice(2)}_${Date.now()}`
}

function isQueryRow(value: unknown): value is QueryRow {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function readString(row: QueryRow, keys: string[]) {
  for (const key of keys) {
    const value = row[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number') return String(value)
  }
  return ''
}

function readNumber(row: QueryRow, keys: string[]) {
  for (const key of keys) {
    const value = row[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) return parsed
    }
  }
  return undefined
}

function normalizeDay(value: string): Course['slots'][number]['day'] | null {
  const normalized = value.trim().toLowerCase()
  if (['mon', 'monday', '월', '월요일'].includes(normalized)) return 'Mon'
  if (['tue', 'tues', 'tuesday', '화', '화요일'].includes(normalized)) return 'Tue'
  if (['wed', 'wednesday', '수', '수요일'].includes(normalized)) return 'Wed'
  if (['thu', 'thur', 'thurs', 'thursday', '목', '목요일'].includes(normalized)) return 'Thu'
  if (['fri', 'friday', '금', '금요일'].includes(normalized)) return 'Fri'
  return null
}

function parseHour(value: string) {
  const match = value.match(/\d{1,2}/)
  if (!match) return null
  const hour = Number(match[0])
  return Number.isFinite(hour) ? hour : null
}

function parseSlots(timeText: string): Course['slots'] {
  const slots: Course['slots'] = []
  const parts = timeText.split(/[,;/]+/)

  for (const part of parts) {
    const match = part.match(
      /(mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|월요일?|화요일?|수요일?|목요일?|금요일?)\s*[\s(]*([0-2]?\d)(?::\d{2})?\s*[-~]\s*([0-2]?\d)(?::\d{2})?/i,
    )
    if (!match) continue

    const day = normalizeDay(match[1])
    const startHour = parseHour(match[2])
    const endHour = parseHour(match[3])
    if (!day || startHour === null || endHour === null || endHour <= startHour) continue
    slots.push({ day, startHour, endHour })
  }

  return slots
}

function rowToCourse(row: QueryRow, index: number): Course {
  const subjectCode = readString(row, [
    'subject_code',
    'course_code',
    'course_id',
    'id',
    'code',
  ])
  const section = readString(row, ['section', 'class_no', 'division'])
  const id = subjectCode
    ? section
      ? `${subjectCode}-${section}`
      : subjectCode
    : `DB-${index + 1}`
  const name =
    readString(row, ['subject_name', 'course_name', 'name', 'title']) ||
    `Course ${index + 1}`
  const professor =
    readString(row, ['professor', 'instructor', 'teacher', '교수']) || '-'
  const credits = readNumber(row, ['credit_hours', 'credits', 'credit', '학점']) ?? 0
  const timeText =
    readString(row, ['lecture_time', 'time_text', 'schedule', 'time', '시간']) ||
    'Time TBA'
  const capacity = readNumber(row, ['capacity', '정원'])
  const enrolled = readNumber(row, ['enrolled', 'registered', '수강인원'])
  const status =
    capacity !== undefined && enrolled !== undefined && enrolled >= capacity
      ? 'Closed'
      : 'Open'

  return {
    id,
    name,
    professor,
    credits,
    status,
    timeText,
    slots: parseSlots(timeText),
  }
}

function rowsToCourses(rows: unknown[]) {
  return rows.filter(isQueryRow).map(rowToCourse)
}

export default function ChatPopup({
  open,
  onClose,
  allCourses,
  selectedCourses,
  selectedIds,
  onAddCourse,
  onOpenExpandedTimetable,
}: {
  open: boolean
  onClose: () => void
  allCourses: Course[]
  selectedCourses: Course[]
  selectedIds: Set<string>
  onAddCourse: (course: Course) => void
  onOpenExpandedTimetable: () => void
}) {
  const [mounted, setMounted] = useState(false)
  const [visible, setVisible] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: makeId('sys'),
      role: 'system',
      text: '안녕하세요! 원하는 과목 키워드를 입력하면 검색 결과와 시간표를 보여드릴게요.',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [lastSql, setLastSql] = useState('')
  const [lastWarning, setLastWarning] = useState('')
  const [lastError, setLastError] = useState('')
  const [dbCourses, setDbCourses] = useState<Course[] | null>(null)

  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) {
      setVisible(false)
      const t = window.setTimeout(() => setMounted(false), 180)
      return () => window.clearTimeout(t)
    }
    setMounted(true)
    const t = window.setTimeout(() => setVisible(true), 10)
    return () => window.clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!mounted) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mounted, onClose])

  useEffect(() => {
    if (!mounted) return
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [mounted, messages.length])

  const results = useMemo(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')?.text ?? ''
    const q = lastUser.trim().toLowerCase()
    const sourceCourses = dbCourses ?? allCourses
    if (dbCourses) return sourceCourses.slice(0, 6)
    if (!q) return sourceCourses.slice(0, 5)
    const hits = sourceCourses.filter((c) => {
      const hay = `${c.id} ${c.name} ${c.professor} ${c.timeText}`.toLowerCase()
      return hay.includes(q) || (q.includes('db') && hay.includes('database'))
    })
    return (hits.length ? hits : sourceCourses.slice(0, 5)).slice(0, 6)
  }, [allCourses, dbCourses, messages])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setLastError('')
    setLastWarning('')
    setDbCourses(null)

    setMessages((prev) => [
      ...prev,
      { id: makeId('usr'), role: 'user', text },
    ])

    setLoading(true)

    try {
      const res = await fetch('/api/v1/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text }),
      })
      const payload = (await res.json()) as QueryApiResponse

      if (!res.ok || payload.error) {
        const errorText =
          payload.error ??
          `요청 처리에 실패했습니다. (${res.status})`
        setLastError(errorText)
        setDbCourses(null)
        setMessages((prev) => [
          ...prev,
          {
            id: makeId('sys'),
            role: 'system',
            text: `요청 실패: ${errorText}`,
          },
        ])
        return
      }

      setLastSql(payload.sql ?? '')
      setLastWarning(payload.warning ?? '')

      const rowCount = Array.isArray(payload.data) ? payload.data.length : 0
      const nextDbCourses =
        !payload.warning && Array.isArray(payload.data)
          ? rowsToCourses(payload.data)
          : null
      setDbCourses(nextDbCourses)
      const summary = payload.warning
        ? 'SQL 생성 완료 (DB 미연결로 결과 조회는 생략되었습니다).'
        : `SQL 실행 완료: ${rowCount}건 결과를 받았습니다.`

      setMessages((prev) => [
        ...prev,
        {
          id: makeId('sys'),
          role: 'system',
          text: summary,
        },
      ])
    } catch {
      const errorText = '백엔드 연결에 실패했습니다. 서버 실행 상태를 확인해주세요.'
      setLastError(errorText)
      setDbCourses(null)
      setMessages((prev) => [
        ...prev,
        {
          id: makeId('sys'),
          role: 'system',
          text: `요청 실패: ${errorText}`,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  if (!mounted) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end p-4 sm:p-6">
      <button
        type="button"
        aria-label="Close assistant"
        onClick={onClose}
        className={cn(
          'absolute inset-0 bg-slate-900/30 backdrop-blur-[1px] transition-opacity duration-200',
          visible ? 'opacity-100' : 'opacity-0',
        )}
      />

      <div
        className={cn(
          'relative w-full max-w-md overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl transition duration-200',
          visible ? 'opacity-100 scale-100' : 'opacity-0 scale-95',
        )}
        role="dialog"
        aria-modal="true"
        aria-label="AI Course Assistant"
      >
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">
              AI Course Assistant
            </div>
            <div className="text-xs text-slate-500">
              Course search · timetable preview
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
            aria-label="Close"
          >
            <span className="text-lg leading-none">×</span>
          </button>
        </div>

        <div className="flex max-h-[76vh] flex-col">
          <div className="px-4 pt-4">
            <div
              ref={scrollRef}
              className="h-52 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-3"
            >
              <div className="space-y-2">
                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={cn(
                      'flex',
                      m.role === 'user' ? 'justify-end' : 'justify-start',
                    )}
                  >
                    <div
                      className={cn(
                        'max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-sm',
                        m.role === 'user'
                          ? 'bg-blue-600 text-white'
                          : 'bg-white text-slate-800 ring-1 ring-slate-200',
                      )}
                    >
                      {m.text}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="px-4 py-3">
            <div className="flex items-center gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') send()
                }}
                placeholder="e.g. 데이터베이스, 네트워크, ML..."
                disabled={loading}
                className="h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
              />
              <button
                type="button"
                onClick={send}
                disabled={loading}
                className="h-10 shrink-0 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 active:bg-blue-700"
              >
                {loading ? '...' : 'Send'}
              </button>
            </div>
            {lastWarning && (
              <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {lastWarning}
              </div>
            )}
            {lastError && (
              <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {lastError}
              </div>
            )}
            {lastSql && (
              <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="mb-1 text-[11px] font-semibold text-slate-600">
                  Generated SQL
                </div>
                <pre className="overflow-x-auto whitespace-pre-wrap break-all text-[11px] text-slate-700">
                  {lastSql}
                </pre>
              </div>
            )}
          </div>

          <div className="border-t border-slate-200 px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold text-slate-700">
                Course results
              </div>
              <div className="text-xs text-slate-500">
                {results.length} items
              </div>
            </div>
            <div className="mt-2 space-y-2">
              {results.map((c) => {
                const already = selectedIds.has(c.id)
                return (
                  <div
                    key={c.id}
                    className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-slate-900">
                        {c.name}
                      </div>
                      <div className="truncate text-xs text-slate-500">
                        {c.timeText}
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={already}
                      onClick={() => onAddCourse(c)}
                      className={cn(
                        'h-9 shrink-0 rounded-lg px-3 text-xs font-semibold transition',
                        already
                          ? 'cursor-not-allowed bg-slate-100 text-slate-400'
                          : 'bg-blue-50 text-blue-700 hover:bg-blue-100',
                      )}
                    >
                      {already ? 'Added' : 'Add'}
                    </button>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="border-t border-slate-200 bg-white px-4 py-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-xs font-semibold text-slate-700">
                Mini timetable
              </div>
              <div className="text-xs text-slate-500">
                {selectedCourses.length} selected
              </div>
            </div>
            <Timetable
              courses={selectedCourses}
              variant="mini"
              onClick={onOpenExpandedTimetable}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

