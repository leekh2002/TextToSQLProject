import type { CourseItemApi, WeekdayApi } from '../types/api'
import type { Course, Weekday } from '../types/course'

const weekdayMap: Record<WeekdayApi, Weekday | null> = {
  MON: 'Mon',
  TUE: 'Tue',
  WED: 'Wed',
  THU: 'Thu',
  FRI: 'Fri',
  SAT: null,
  SUN: null,
}

function parseHour(value: string) {
  const match = value.match(/\d{1,2}/)
  if (!match) return null
  const hour = Number(match[0])
  return Number.isFinite(hour) ? hour : null
}

function apiStatus(course: CourseItemApi): Course['status'] {
  if (
    typeof course.capacity === 'number' &&
    typeof course.enrolled === 'number' &&
    course.enrolled >= course.capacity
  ) {
    return 'Closed'
  }
  return 'Open'
}

export function apiCourseToCourse(course: CourseItemApi): Course {
  const slots = course.schedule
    .map((slot) => {
      const day = weekdayMap[slot.day]
      const startHour = parseHour(slot.start)
      const endHour = parseHour(slot.end)
      if (!day || startHour === null || endHour === null || endHour <= startHour) {
        return null
      }
      return { day, startHour, endHour }
    })
    .filter((slot): slot is Course['slots'][number] => slot !== null)

  const timeText =
    course.lectureTime ||
    course.schedule
      .map((slot) => `${slot.day} ${slot.start}-${slot.end}`)
      .join(', ') ||
    'Time TBA'

  return {
    id: course.courseId,
    name: course.name,
    professor: course.professor,
    credits: course.credits,
    status: apiStatus(course),
    timeText,
    slots,
  }
}
