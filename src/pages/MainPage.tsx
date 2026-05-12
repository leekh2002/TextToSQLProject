import { useEffect, useMemo, useState } from 'react'
import ChatPopup from '../components/ChatPopup'
import CourseTable from '../components/CourseTable'
import ExpandedTimetableModal from '../components/ExpandedTimetableModal'
import Timetable from '../components/Timetable'
import { mockCourses } from '../mock/courses'
import { coursesApi } from '../services/api'
import type { Course } from '../types/course'
import { cn } from '../utils/cn'
import { apiCourseToCourse } from '../utils/courseMapper'

function ChatIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M7.5 20.5c1.6.5 3.2.8 4.5.8 5.2 0 9-3.6 9-8.4S17.2 4.5 12 4.5 3 8.1 3 12.9c0 1.9.6 3.6 1.8 5.1l-.6 3.2 3.1-.9c.4.2.8.4 1.2.6Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="M7.7 12.7h.8m3.1 0h.8m3.1 0h.8"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

type MainPageProps = {
  userName?: string
  onLoginClick: () => void
  onLogout: () => void
}

export default function MainPage({
  userName,
  onLoginClick,
  onLogout,
}: MainPageProps) {
  const [allCourses, setAllCourses] = useState<Course[]>(mockCourses)
  const [popupOpen, setPopupOpen] = useState(false)
  const [expandedOpen, setExpandedOpen] = useState(false)
  const [selectedCourses, setSelectedCourses] = useState<Course[]>([])

  useEffect(() => {
    let disposed = false

    async function loadCourses() {
      try {
        const result = await coursesApi.getCourses({
          year: new Date().getFullYear(),
          semester: '1',
          page: 1,
          pageSize: 200,
        })
        const courses = result.items.map(apiCourseToCourse)
        if (!disposed && courses.length > 0) {
          setAllCourses(courses)
        }
      } catch {
        if (!disposed) {
          setAllCourses(mockCourses)
        }
      }
    }

    void loadCourses()

    return () => {
      disposed = true
    }
  }, [])

  const selectedIds = useMemo(
    () => new Set(selectedCourses.map((c) => c.id)),
    [selectedCourses],
  )

  function addCourse(course: Course) {
    setSelectedCourses((prev) => {
      if (prev.some((c) => c.id === course.id)) return prev
      return [...prev, course]
    })
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm">
              <span className="text-sm font-black">UNI</span>
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-900">
                Course Registration
              </div>
              <div className="text-xs text-slate-500">
                Main course browser
              </div>
            </div>
          </div>

          <div className="ml-auto w-full max-w-xl">
            <div className="relative">
              <input
                placeholder="Search courses (UI only)"
                className="h-11 w-full rounded-xl border border-slate-200 bg-white px-4 pr-12 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
              />
              <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-slate-400">
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  aria-hidden="true"
                >
                  <path
                    d="M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                  />
                  <path
                    d="M16.2 16.2 21 21"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {userName ? (
              <>
                <div className="hidden rounded-lg bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 sm:block">
                  {userName}
                </div>
                <button
                  type="button"
                  onClick={onLogout}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
                >
                  Logout
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={onLoginClick}
                className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-blue-700"
              >
                Login
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-5 px-4 py-6 sm:px-6 lg:grid-cols-[1.45fr_0.95fr]">
        <section className="min-w-0">
          <CourseTable courses={allCourses} selectedIds={selectedIds} />
        </section>

        <aside className="space-y-5">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-slate-900">
                  Selected Courses
                </div>
                <div className="text-xs text-slate-500">
                  Added via the assistant popup
                </div>
              </div>
              <div className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
                {selectedCourses.length}
              </div>
            </div>

            <div className="mt-3 space-y-2">
              {selectedCourses.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-600">
                  Open the assistant and add a course to build your timetable.
                </div>
              ) : (
                selectedCourses.map((c) => (
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
                    <div className="shrink-0 text-xs font-semibold text-slate-600">
                      {c.credits}cr
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <Timetable
            courses={selectedCourses}
            variant="mini"
            onClick={() => setExpandedOpen(true)}
          />
        </aside>
      </main>

      <button
        type="button"
        onClick={() => setPopupOpen(true)}
        className={cn(
          'fixed bottom-6 right-6 z-40 inline-flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-xl',
          'transition hover:bg-blue-700 active:scale-[0.98]',
        )}
        aria-label="Open AI Course Assistant"
      >
        <ChatIcon className="h-6 w-6" />
      </button>

      <ChatPopup
        open={popupOpen}
        onClose={() => setPopupOpen(false)}
        allCourses={allCourses}
        selectedCourses={selectedCourses}
        selectedIds={selectedIds}
        onAddCourse={addCourse}
        onOpenExpandedTimetable={() => setExpandedOpen(true)}
      />

      <ExpandedTimetableModal
        open={expandedOpen}
        courses={selectedCourses}
        onClose={() => setExpandedOpen(false)}
      />
    </div>
  )
}
