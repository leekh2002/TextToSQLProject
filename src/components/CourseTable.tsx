import type { Course } from '../types/course'
import { cn } from '../utils/cn'

const statusStyles: Record<Course['status'], string> = {
  Open: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  Closed: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
  Waitlist: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
}

export default function CourseTable({
  courses,
  selectedIds,
}: {
  courses: Course[]
  selectedIds: Set<string>
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            Course List
          </div>
          <div className="text-xs text-slate-500">
            {courses.length} courses
          </div>
        </div>
        <div className="text-xs text-slate-500">
          Selected: <span className="font-semibold">{selectedIds.size}</span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] table-auto">
          <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-600">
            <tr>
              <th className="px-5 py-3">Course Name</th>
              <th className="px-5 py-3">Professor</th>
              <th className="px-5 py-3">Time</th>
              <th className="px-5 py-3">Credits</th>
              <th className="px-5 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-sm">
            {courses.map((c) => (
              <tr
                key={c.id}
                className={cn(
                  'hover:bg-slate-50/70',
                  selectedIds.has(c.id) && 'bg-blue-50/40',
                )}
              >
                <td className="px-5 py-4">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-blue-600/90" />
                    <div>
                      <div className="font-semibold text-slate-900">
                        {c.name}
                      </div>
                      <div className="text-xs text-slate-500">{c.id}</div>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-4 text-slate-700">{c.professor}</td>
                <td className="px-5 py-4 text-slate-700">{c.timeText}</td>
                <td className="px-5 py-4 text-slate-700">{c.credits}</td>
                <td className="px-5 py-4">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold',
                      statusStyles[c.status],
                    )}
                  >
                    {c.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

