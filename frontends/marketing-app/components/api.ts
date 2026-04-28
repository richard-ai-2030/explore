export async function callApi(path: string, method: string, body?: any, token?: string) {
  const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || '/api').replace(/\/$/, '');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBase}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(data?.detail || data?.error || text || 'Request failed');
  return data;
}
