import type { ApiError } from '../types/api'

const TOKEN_STORAGE_KEY = 'course-frontend-auth-token'
const DEFAULT_BASE_URL = '/api/v1'

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

type RequestOptions = {
  method?: HttpMethod
  body?: unknown
  headers?: Record<string, string>
  useAuth?: boolean
  signal?: AbortSignal
}

function normalizeBaseUrl(url: string) {
  return url.endsWith('/') ? url.slice(0, -1) : url
}

function buildQuery(params?: Record<string, unknown>) {
  if (!params) return ''
  const searchParams = new URLSearchParams()

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    searchParams.set(key, String(value))
  }

  const query = searchParams.toString()
  return query ? `?${query}` : ''
}

function readMessageFromJson(json: unknown) {
  if (
    json &&
    typeof json === 'object' &&
    'error' in json &&
    json.error &&
    typeof json.error === 'object' &&
    'message' in json.error &&
    typeof json.error.message === 'string'
  ) {
    return json.error.message
  }
  if (json && typeof json === 'object' && 'message' in json && typeof json.message === 'string') {
    return json.message
  }
  return null
}

export class HttpError extends Error {
  status: number
  payload?: ApiError | unknown

  constructor(status: number, message: string, payload?: ApiError | unknown) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.payload = payload
  }
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = normalizeBaseUrl(baseUrl)
  }

  async request<TResponse>(
    path: string,
    query?: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<TResponse> {
    const method = options?.method ?? 'GET'
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    }
    const useAuth = options?.useAuth ?? true
    if (useAuth) {
      const token = localStorage.getItem(TOKEN_STORAGE_KEY)
      if (token) headers.Authorization = `Bearer ${token}`
    }

    const response = await fetch(`${this.baseUrl}${path}${buildQuery(query)}`, {
      method,
      headers,
      body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options?.signal,
    })

    const contentType = response.headers.get('content-type') ?? ''
    const isJson = contentType.includes('application/json')
    const payload = isJson ? ((await response.json()) as unknown) : undefined

    if (!response.ok) {
      const message = readMessageFromJson(payload) ?? `Request failed: ${response.status}`
      throw new HttpError(response.status, message, payload)
    }

    return payload as TResponse
  }

  get<TResponse>(path: string, query?: Record<string, unknown>, useAuth = true) {
    return this.request<TResponse>(path, query, { method: 'GET', useAuth })
  }

  post<TResponse>(path: string, body?: unknown, useAuth = true) {
    return this.request<TResponse>(path, undefined, { method: 'POST', body, useAuth })
  }

  put<TResponse>(path: string, body?: unknown, useAuth = true) {
    return this.request<TResponse>(path, undefined, { method: 'PUT', body, useAuth })
  }

  patch<TResponse>(path: string, body?: unknown, useAuth = true) {
    return this.request<TResponse>(path, undefined, { method: 'PATCH', body, useAuth })
  }

  delete<TResponse>(path: string, useAuth = true) {
    return this.request<TResponse>(path, undefined, { method: 'DELETE', useAuth })
  }
}

const baseUrl = import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_BASE_URL
export const apiClient = new ApiClient(baseUrl)

export function setAccessToken(token: string) {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearAccessToken() {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}
