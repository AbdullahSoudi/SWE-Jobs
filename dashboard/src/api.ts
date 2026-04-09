import { createClient } from '@supabase/supabase-js';
import type { JobSearchResponse, StatsSummary, SalaryStats, TrendsResponse } from './types';

// Supabase client (read-only via anon key)
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || '';
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || '';
export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Custom API base (FastAPI on Render/Railway)
const API_BASE = import.meta.env.VITE_API_BASE || '';

async function fetchApi<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  searchJobs: (params: Record<string, string>) =>
    fetchApi<JobSearchResponse>('/api/jobs/search', params),

  getStatsSummary: () =>
    fetchApi<StatsSummary>('/api/stats/summary'),

  getSalaryStats: (params: Record<string, string>) =>
    fetchApi<SalaryStats>('/api/stats/salary', params),

  getTrends: (period: string = '7d') =>
    fetchApi<TrendsResponse>('/api/stats/trends', { period }),
};
