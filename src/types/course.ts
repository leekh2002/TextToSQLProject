export type Weekday = 'Mon' | 'Tue' | 'Wed' | 'Thu' | 'Fri'

export type CourseTimeSlot = {
  day: Weekday
  startHour: number
  endHour: number
}

export type Course = {
  id: string
  name: string
  professor: string
  credits: number
  status: 'Open' | 'Closed' | 'Waitlist'
  timeText: string
  slots: CourseTimeSlot[]
}

