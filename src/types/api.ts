export type Semester = '1' | 'summer' | '2' | 'winter'

export type WeekdayApi = 'MON' | 'TUE' | 'WED' | 'THU' | 'FRI' | 'SAT' | 'SUN'

export type ApiErrorCode =
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'VALIDATION_ERROR'
  | 'COURSE_NOT_FOUND'
  | 'INTERNAL_ERROR'
  | string

export type ApiError = {
  error: {
    code: ApiErrorCode
    message: string
    details?: Record<string, unknown>
  }
}

export type UserProfile = {
  id: string
  studentNo: string
  name: string
  departmentCode: string
  departmentName: string
  grade: number
  majorType?: 'MAIN' | 'DOUBLE' | 'MINOR'
  admissionYear?: number
  requirementVersion?: string
}

export type LoginRequest = {
  studentNo: string
  password: string
}

export type SignupRequest = {
  studentNo: string
  name: string
  password: string
  departmentCode: string
}

export type AuthTokens = {
  accessToken: string
  refreshToken?: string
  expiresIn?: number
}

export type LoginResponse = AuthTokens & {
  user: UserProfile
}

export type RefreshResponse = {
  accessToken: string
  expiresIn?: number
}

export type CourseScheduleSlotApi = {
  day: WeekdayApi
  start: string
  end: string
  room?: string
}

export type CourseItemApi = {
  courseId: string
  name: string
  departmentCode: string
  departmentName?: string
  credits: number
  professor: string
  capacity?: number
  enrolled?: number
  schedule: CourseScheduleSlotApi[]
  lectureTime?: string
  section?: string
  tags?: string[]
}

export type CoursesQuery = {
  year: number
  semester: Semester
  departmentCode?: string
  keyword?: string
  day?: WeekdayApi
  timeFrom?: string
  timeTo?: string
  credits?: number
  page?: number
  pageSize?: number
}

export type RecommendedCoursesQuery = {
  year: number
  semester: Semester
  excludeCompleted?: boolean
  onlyRequired?: boolean
  excludeTimeConflictWithPlan?: boolean
  page?: number
  pageSize?: number
}

export type PaginatedResponse<T> = {
  items: T[]
  page: number
  pageSize: number
  total: number
}

export type GraduationSummary = {
  requiredMajorEarned: number
  requiredMajorTarget: number
  generalEarned: number
  generalTarget: number
  graduationEligible: boolean
}

export type GraduationBlock = {
  code: string
  name: string
  earned: number
  target: number
  remaining: number
}

export type GraduationStatusResponse = {
  requirementVersion: string
  summary: GraduationSummary
  blocks: GraduationBlock[]
}
