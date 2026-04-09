import type { Job } from '../types';

const SENIORITY_COLORS: Record<string, string> = {
  intern: 'bg-purple-100 text-purple-700',
  junior: 'bg-green-100 text-green-700',
  mid: 'bg-blue-100 text-blue-700',
  senior: 'bg-orange-100 text-orange-700',
  lead: 'bg-red-100 text-red-700',
  executive: 'bg-gray-800 text-white',
};

export default function JobCard({ job }: { job: Job }) {
  const salaryDisplay = job.salary_min && job.salary_max
    ? `${job.salary_currency || '$'}${job.salary_min.toLocaleString()} - ${job.salary_max.toLocaleString()}`
    : job.salary_raw || null;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <h3 className="font-semibold text-gray-900">{job.title}</h3>
          <p className="text-sm text-gray-600">{job.company || 'Unknown'}</p>
        </div>
        <span className={`text-xs px-2 py-1 rounded-full ${SENIORITY_COLORS[job.seniority] || SENIORITY_COLORS.mid}`}>
          {job.seniority}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-500">
        <span>{job.location || 'Not specified'}</span>
        {job.is_remote && <span className="text-green-600">Remote</span>}
        {salaryDisplay && <span className="text-green-700 font-medium">{salaryDisplay}</span>}
        <span>{job.original_source || job.source}</span>
      </div>
      {job.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {job.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
              {tag}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          Apply &rarr;
        </a>
      </div>
    </div>
  );
}
