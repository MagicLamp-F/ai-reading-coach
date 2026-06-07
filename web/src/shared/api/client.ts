import { z } from 'zod';

export const ApiErrorSchema = z.object({
  detail: z.union([z.string(), z.array(z.unknown()), z.record(z.unknown())]).optional(),
});

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  return readJson<T>(response);
}

export async function apiPost<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<T>(response);
}

export async function apiDelete<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<T>(response);
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    body: formData,
  });
  return readJson<T>(response);
}

async function readJson<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const parsed = ApiErrorSchema.safeParse(data);
    const detail = parsed.success ? parsed.data.detail : undefined;
    throw new Error(typeof detail === 'string' ? detail : `请求失败：${response.status}`);
  }
  return data as T;
}

export function searchParams() {
  return new URLSearchParams(window.location.search);
}
