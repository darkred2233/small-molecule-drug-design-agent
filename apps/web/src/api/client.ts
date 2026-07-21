import axios from 'axios';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

const client = axios.create({ baseURL: API_BASE_URL, timeout: 60_000 });

function messageFrom(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('；');
    return error.message;
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试。';
}

export const api = {
  async get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    try { return (await client.get<T>(url, { params })).data; } catch (error) { throw new Error(messageFrom(error)); }
  },
  async post<T>(url: string, body?: unknown): Promise<T> {
    try { return (await client.post<T>(url, body)).data; } catch (error) { throw new Error(messageFrom(error)); }
  },
  async put<T>(url: string, body?: unknown): Promise<T> {
    try { return (await client.put<T>(url, body)).data; } catch (error) { throw new Error(messageFrom(error)); }
  },
  async delete<T>(url: string): Promise<T> {
    try { return (await client.delete<T>(url)).data; } catch (error) { throw new Error(messageFrom(error)); }
  },
  async upload<T>(url: string, file: File, onProgress?: (progress: number) => void): Promise<T> {
    const form = new FormData();
    form.append('file', file);
    try {
      return (await client.post<T>(url, form, { headers: { 'Content-Type': 'multipart/form-data' }, onUploadProgress: (event) => onProgress?.(event.total ? Math.round((event.loaded / event.total) * 100) : 0) })).data;
    } catch (error) { throw new Error(messageFrom(error)); }
  },
};

export function apiUrl(path: string): string {
  return `${API_BASE_URL.replace(/\/$/, '')}${path}`;
}
