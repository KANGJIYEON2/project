// 대화 히스토리 (thread) localStorage 저장. ID 게이팅과는 별개로 브라우저 전체에서 공유.
import type { Citation } from './types';

export interface ThreadMessage {
  id?: string;
  role: 'user' | 'bot';
  text: string;
  citations?: Citation[];
}

export interface Thread {
  id: string;
  title: string;
  messages: ThreadMessage[];
  createdAt: number;
  updatedAt: number;
}

const KEY = 'jongsose-helper.threads.v1';
const MAX_THREADS = 50;

export function loadThreads(): Thread[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Thread[]) : [];
  } catch {
    return [];
  }
}

export function saveThreads(threads: Thread[]) {
  if (typeof window === 'undefined') return;
  // 최근 MAX_THREADS개만 유지 (오래된 것부터 제거)
  const trimmed = [...threads]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_THREADS);
  localStorage.setItem(KEY, JSON.stringify(trimmed));
}

export function upsertThread(threads: Thread[], thread: Thread): Thread[] {
  const idx = threads.findIndex((t) => t.id === thread.id);
  if (idx === -1) return [thread, ...threads];
  const next = [...threads];
  next[idx] = thread;
  return next;
}

export function deleteThread(threads: Thread[], id: string): Thread[] {
  return threads.filter((t) => t.id !== id);
}

export function genThreadId(): string {
  return `t_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

// 첫 user 메시지의 앞부분을 thread 제목으로.
export function autoTitle(messages: ThreadMessage[]): string {
  const firstUser = messages.find((m) => m.role === 'user');
  if (!firstUser) return '새 대화';
  const t = firstUser.text.replace(/\n+/g, ' ').trim();
  return t.slice(0, 28) || '새 대화';
}

// 사이드바 표시용 — 최근 업데이트순 정렬.
export function sortedThreads(threads: Thread[]): Thread[] {
  return [...threads].sort((a, b) => b.updatedAt - a.updatedAt);
}
