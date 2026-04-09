import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import type { Job } from '../types';
import JobCard from '../components/JobCard';
import FilterBar from '../components/FilterBar';

export default function Home() {
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);

  const page = parseInt(searchParams.get('page') || '1');

  const fetchJobs = (params?: Record<string, string>) => {
    const p = params || Object.fromEntries(searchParams.entries());
    setLoading(true);
    api.searchJobs(p)
      .then((res) => {
        setJobs(res.jobs);
        setTotal(res.total);
        setTotalPages(res.total_pages);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchJobs();
  }, [searchParams.toString()]);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-4">Programming Jobs</h1>
      <FilterBar onSearch={fetchJobs} />

      {loading ? (
        <p className="text-gray-500 py-8">Loading...</p>
      ) : jobs.length === 0 ? (
        <p className="text-gray-500 py-8">No jobs found. Try different filters.</p>
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-3">{total} jobs found</p>
          <div className="grid gap-3">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>
          {totalPages > 1 && (
            <div className="flex justify-center gap-2 mt-6">
              {page > 1 && (
                <a href={`?page=${page - 1}`} className="px-3 py-1 border rounded text-sm">Prev</a>
              )}
              <span className="px-3 py-1 text-sm text-gray-500">Page {page} of {totalPages}</span>
              {page < totalPages && (
                <a href={`?page=${page + 1}`} className="px-3 py-1 border rounded text-sm">Next</a>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
