import { create } from 'zustand';
import type { Status } from './types';

interface Store {
  token: string; setToken: (value: string) => void;
  status: Status | null; setStatus: (value: Status | null) => void;
  live: boolean; setLive: (value: boolean) => void;
}
export const useStore = create<Store>((set) => ({
  token: sessionStorage.getItem('openplayout-token') || '',
  setToken: (token) => { sessionStorage.setItem('openplayout-token', token); set({token, status: null}); },
  status: null, setStatus: (status) => set({status}),
  live: false, setLive: (live) => set({live}),
}));

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: {Authorization: `Bearer ${useStore.getState().token}`, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail: response.statusText}));
    throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
  }
  return response.json() as Promise<T>;
}

export function time(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—';
  const seconds = Math.max(0, Math.floor(value));
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(v => String(v).padStart(2, '0')).join(':');
}
