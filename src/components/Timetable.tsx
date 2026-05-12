import type { ElementType } from 'react'
import type { Course, Weekday } from '../types/course'
import { cn } from '../utils/cn'

const days: Weekday[] = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

function dayLabel(d: Weekday) {
  switch (d) {
    case 'Mon':
      return 'Mon'
    case 'Tue':
      return 'Tue'
    case 'Wed':
      return 'Wed'
    case 'Thu':
      return 'Thu'
    case 'Fri':
      return 'Fri'
  }
}

function courseColor(id: string) {
  const palette = [
    'bg-blue-600/90 ring-blue-200',
    'bg-indigo-600/90 ring-indigo-200',
    'bg-sky-600/90 ring-sky-200',
    'bg-cyan-600/90 ring-cyan-200',
    'bg-violet-600/90 ring-violet-200',
    'bg-emerald-600/90 ring-emerald-200',
    'bg-rose-600/90 ring-rose-200',
  ]
  let hash = 0
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  return palette[hash % palette.length]
}

export default function Timetable({
  courses,
  variant,
  onClick,
}: {
  courses: Course[]
  variant: 'mini' | 'full'
  onClick?: () => void
}) {
  const startHour = 9
  const endHour = 18
  const hours = Array.from({ length: endHour - startHour + 1 }, (_, i) => startHour + i)

  const hourHeight = variant === 'mini' ? 16 : 44
  const totalHeight = (endHour - startHour) * hourHeight

  const Wrapper: ElementType = onClick ? 'button' : 'div'
  const wrapperProps = onClick
    ? {
        type: 'button' as const,
        onClick,
        role: 'button' as const,
        tabIndex: 0,
        'aria-label':
          variant === 'mini' ? 'Open expanded timetable' : 'Timetable',
      }
    : {
        role: 'region' as const,
        'aria-label': 'Timetable',
      }

  return (
    <Wrapper
      {...wrapperProps}
      className={cn(
        'w-full text-left',
        onClick && 'cursor-pointer',
        !onClick && 'cursor-default',
      )}
    >
      <div
        className={cn(
          'rounded-xl border border-slate-200 bg-white shadow-sm',
          variant === 'mini' ? 'p-3' : 'p-4',
          onClick && 'transition hover:shadow-md',
        )}
      >
        <div className="flex items-center justify-between">
          <div className={cn('font-semibold text-slate-900', variant === 'mini' ? 'text-sm' : 'text-base')}>
            Timetable
          </div>
          {variant === 'mini' ? (
            <div className="text-xs text-slate-500">Click to expand</div>
          ) : (
            <div className="text-sm text-slate-500">{courses.length} selected</div>
          )}
        </div>

        <div className={cn('mt-3', variant === 'mini' ? 'text-[10px]' : 'text-xs')}>
          <div className="grid grid-cols-[42px_1fr] gap-2">
            <div className="pt-7 text-slate-400">
              {hours.slice(0, -1).map((h) => (
                <div
                  key={h}
                  className="flex items-start justify-end pr-1"
                  style={{ height: hourHeight }}
                >
                  {h}
                </div>
              ))}
            </div>

            <div className="grid grid-cols-5 gap-2">
              {days.map((d) => (
                <div key={d} className="min-w-0">
                  <div className="mb-1.5 text-center font-semibold text-slate-600">
                    {dayLabel(d)}
                  </div>
                  <div
                    className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-50"
                    style={{ height: totalHeight }}
                  >
                    {hours.slice(0, -1).map((h) => (
                      <div
                        key={`${d}-${h}`}
                        className="border-b border-slate-200/70"
                        style={{ height: hourHeight }}
                      />
                    ))}

                    {courses.flatMap((c) =>
                      c.slots
                        .filter((s) => s.day === d)
                        .map((s) => {
                          const top = (s.startHour - startHour) * hourHeight
                          const height = Math.max(1, (s.endHour - s.startHour) * hourHeight)
                          return (
                            <div
                              key={`${c.id}-${d}-${s.startHour}-${s.endHour}`}
                              className={cn(
                                'absolute left-1 right-1 rounded-md px-2 py-1 text-white shadow-sm ring-1',
                                courseColor(c.id),
                              )}
                              style={{ top, height }}
                              title={`${c.name} (${s.startHour}:00-${s.endHour}:00)`}
                            >
                              <div className={cn('truncate font-semibold', variant === 'mini' ? 'text-[10px]' : 'text-xs')}>
                                {c.name}
                              </div>
                              {variant === 'full' ? (
                                <div className="mt-0.5 truncate text-[11px] opacity-90">
                                  {s.startHour}:00–{s.endHour}:00
                                </div>
                              ) : null}
                            </div>
                          )
                        }),
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {courses.length === 0 ? (
            <div className="mt-3 rounded-lg border border-dashed border-slate-200 bg-white px-3 py-2 text-slate-500">
              Add courses from the assistant to visualize your schedule.
            </div>
          ) : null}
        </div>
      </div>
    </Wrapper>
  )
}

