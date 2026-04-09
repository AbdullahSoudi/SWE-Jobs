import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { api } from '../api';
import type { StatsSummary } from '../types';

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];

export default function Stats() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getStatsSummary()
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-gray-500 py-8">Loading...</p>;
  if (!stats) return <p className="text-gray-500 py-8">Failed to load stats.</p>;

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Statistics</h1>

      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="bg-white rounded-lg border p-4 text-center">
          <p className="text-3xl font-bold text-blue-600">{stats.jobs_today}</p>
          <p className="text-sm text-gray-500">Today</p>
        </div>
        <div className="bg-white rounded-lg border p-4 text-center">
          <p className="text-3xl font-bold text-green-600">{stats.jobs_week}</p>
          <p className="text-sm text-gray-500">This Week</p>
        </div>
        <div className="bg-white rounded-lg border p-4 text-center">
          <p className="text-3xl font-bold text-gray-700">{stats.jobs_total}</p>
          <p className="text-sm text-gray-500">All Time</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold text-gray-900 mb-4">Jobs by Source (7 days)</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={stats.by_source}>
              <XAxis dataKey="source" tick={{ fontSize: 12 }} />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold text-gray-900 mb-4">Jobs by Topic (7 days)</h2>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={stats.by_topic}
                dataKey="count"
                nameKey="topic"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={({ name }) => name}
              >
                {stats.by_topic.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-lg border p-4 mt-6">
        <h2 className="font-semibold text-gray-900 mb-3">Top Companies (7 days)</h2>
        <div className="grid grid-cols-2 gap-2">
          {stats.top_companies.map((c) => (
            <div key={c.company} className="flex justify-between text-sm">
              <span className="text-gray-700">{c.company}</span>
              <span className="text-gray-500">{c.count} jobs</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
