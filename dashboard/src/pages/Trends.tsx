import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { api } from '../api';
import type { TrendItem } from '../types';

export default function Trends() {
  const [trends, setTrends] = useState<TrendItem[]>([]);
  const [period, setPeriod] = useState('7d');
  const [loading, setLoading] = useState(true);

  const fetchTrends = (p: string) => {
    setLoading(true);
    api.getTrends(p)
      .then((res) => setTrends(res.trends))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchTrends(period);
  }, [period]);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Skill Trends</h1>

      <div className="flex gap-2 mb-6">
        {['7d', '14d', '30d'].map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`px-3 py-1.5 rounded text-sm ${
              period === p
                ? 'bg-blue-600 text-white'
                : 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-gray-500 py-8">Loading...</p>
      ) : (
        <>
          <div className="bg-white rounded-lg border p-4 mb-6">
            <h2 className="font-semibold text-gray-900 mb-4">Top Skills ({period})</h2>
            <ResponsiveContainer width="100%" height={400}>
              <BarChart data={trends} layout="vertical">
                <XAxis type="number" />
                <YAxis dataKey="skill" type="category" width={100} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6">
                  {trends.map((entry, i) => (
                    <Cell key={i} fill={entry.change_percent >= 0 ? '#10b981' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-white rounded-lg border p-4">
            <h2 className="font-semibold text-gray-900 mb-3">Change from Previous Period</h2>
            <div className="grid grid-cols-2 gap-2">
              {trends.map((t) => (
                <div key={t.skill} className="flex justify-between text-sm py-1">
                  <span className="text-gray-700">{t.skill}</span>
                  <span className={t.change_percent >= 0 ? 'text-green-600' : 'text-red-600'}>
                    {t.change_percent >= 0 ? '+' : ''}{t.change_percent}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
