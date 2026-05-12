import type { Course } from '../types/course'

export const mockCourses: Course[] = [
  {
    id: 'CSE301',
    name: 'Database Systems',
    professor: 'Prof. Kim',
    credits: 3,
    status: 'Open',
    timeText: 'Mon 10-12, Wed 10-11',
    slots: [
      { day: 'Mon', startHour: 10, endHour: 12 },
      { day: 'Wed', startHour: 10, endHour: 11 },
    ],
  },
  {
    id: 'CSE214',
    name: 'Operating Systems',
    professor: 'Prof. Lee',
    credits: 3,
    status: 'Open',
    timeText: 'Tue 13-15, Thu 13-14',
    slots: [
      { day: 'Tue', startHour: 13, endHour: 15 },
      { day: 'Thu', startHour: 13, endHour: 14 },
    ],
  },
  {
    id: 'CSE220',
    name: 'Computer Networks',
    professor: 'Prof. Park',
    credits: 3,
    status: 'Waitlist',
    timeText: 'Mon 15-17',
    slots: [{ day: 'Mon', startHour: 15, endHour: 17 }],
  },
  {
    id: 'CSE330',
    name: 'Machine Learning Basics',
    professor: 'Prof. Choi',
    credits: 3,
    status: 'Open',
    timeText: 'Wed 14-16',
    slots: [{ day: 'Wed', startHour: 14, endHour: 16 }],
  },
  {
    id: 'CSE240',
    name: 'Software Engineering',
    professor: 'Prof. Jung',
    credits: 3,
    status: 'Closed',
    timeText: 'Fri 10-12',
    slots: [{ day: 'Fri', startHour: 10, endHour: 12 }],
  },
  {
    id: 'CSE321',
    name: 'Data Mining',
    professor: 'Prof. Han',
    credits: 3,
    status: 'Open',
    timeText: 'Tue 10-12',
    slots: [{ day: 'Tue', startHour: 10, endHour: 12 }],
  },
  {
    id: 'CSE315',
    name: 'Advanced Databases',
    professor: 'Prof. Seo',
    credits: 3,
    status: 'Open',
    timeText: 'Thu 09-11',
    slots: [{ day: 'Thu', startHour: 9, endHour: 11 }],
  },
]

