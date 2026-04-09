import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { api } from '../api';
import type { SalaryStats } from '../types';

export default function Salary() {
  const [stats, setStats] = useState<SalaryStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState('');

  const fetchSalary = (roleQuery?: string) => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (roleQuery) params.role = roleQuery;
    api.getSalaryStats(params)
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSalary();
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Salary Insights</h1>

      <div className="flex gap-3 mb-6">
        <input
          type="text"
          placeholder="Search by role (e.g. python, backend)..."
          value={role}
          onChange={(e) => setRole(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchSalary(role)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm flex-1"
        />
        <button
          onClick={() => fetchSalary(role)}
          className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700"
        >
          Search
        </button>
      </div>

      {loading && <p className="text-gray-500 py-8">Loading...</p>}

      {stats && stats.overall && (
        <>
          <div className="grid grid-cols-4 gap-4 mb-8">
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-gray-700">{stats.overall.sample_size}</p>
              <p className="text-xs text-gray-500">Sample Size</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-green-600">
                ${stats.overall.avg_min?.toLocaleString()} - ${stats.overall.avg_max?.toLocaleString()}
              </p>
              <p className="text-xs text-gray-500">Average Range</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-blue-600">${stats.overall.median_min?.toLocaleString()}</p>
              <p className="text-xs text-gray-500">Median Min</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-orange-600">
                ${stats.overall.lowest?.toLocaleString()} - ${stats.overall.highest?.toLocaleString()}
              </p>
              <p className="text-xs text-gray-500">Full Range</p>
            </div>
          </div>

          {stats.by_seniority.length > 0 && (
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-900 mb-4">Average Salary by Seniority</h2>
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={stats.by_seniority}>
                  <XAxis dataKey="seniority" />
                  <YAxis />
                  <Tooltip formatter={(v) => `$${Number(v).toLocaleString()}`} />
                  <Legend />
                  <Bar dataKey="avg_min" fill="#3b82f6" name="Avg Min" />
                  <Bar dataKey="avg_max" fill="#10b981" name="Avg Max" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
