import { useSearchParams } from 'react-router-dom';

const TOPICS = [
  'backend', 'frontend', 'mobile', 'devops', 'qa',
  'ai_ml', 'cybersecurity', 'gamedev', 'blockchain', 'erp', 'internships',
];

const SENIORITY_LEVELS = ['intern', 'junior', 'mid', 'senior', 'lead', 'executive'];

export default function FilterBar({ onSearch }: { onSearch: (params: Record<string, string>) => void }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const handleChange = (key: string, value: string) => {
    const params = Object.fromEntries(searchParams.entries());
    if (value) {
      params[key] = value;
    } else {
      delete params[key];
    }
    params.page = '1';
    setSearchParams(params);
    onSearch(params);
  };

  return (
    <div className="flex flex-wrap gap-3 mb-4">
      <input
        type="text"
        placeholder="Search jobs..."
        defaultValue={searchParams.get('q') || ''}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleChange('q', (e.target as HTMLInputElement).value);
        }}
        className="border border-gray-300 rounded px-3 py-1.5 text-sm flex-1 min-w-[200px]"
      />
      <select
        defaultValue={searchParams.get('topic') || ''}
        onChange={(e) => handleChange('topic', e.target.value)}
        className="border border-gray-300 rounded px-3 py-1.5 text-sm"
      >
        <option value="">All Topics</option>
        {TOPICS.map((t) => (
          <option key={t} value={t}>{t.replace('_', '/')}</option>
        ))}
      </select>
      <select
        defaultValue={searchParams.get('seniority') || ''}
        onChange={(e) => handleChange('seniority', e.target.value)}
        className="border border-gray-300 rounded px-3 py-1.5 text-sm"
      >
        <option value="">All Levels</option>
        {SENIORITY_LEVELS.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
      <label className="flex items-center gap-1 text-sm text-gray-600">
        <input
          type="checkbox"
          defaultChecked={searchParams.get('remote') === 'true'}
          onChange={(e) => handleChange('remote', e.target.checked ? 'true' : '')}
        />
        Remote
      </label>
    </div>
  );
}
