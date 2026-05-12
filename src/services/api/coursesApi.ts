import { apiClient } from '../apiClient'
import type {
  CourseItemApi,
  CoursesQuery,
  PaginatedResponse,
  RecommendedCoursesQuery,
} from '../../types/api'

export function getCourses(query: CoursesQuery) {
  return apiClient.get<PaginatedResponse<CourseItemApi>>('/courses', query)
}

export function getRecommendedCourses(query: RecommendedCoursesQuery) {
  return apiClient.get<PaginatedResponse<CourseItemApi>>('/courses/recommended', query)
}

export function getCourseById(courseId: string) {
  return apiClient.get<CourseItemApi>(`/courses/${courseId}`)
}
