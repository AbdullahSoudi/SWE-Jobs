import { Link, Outlet, useLocation } from 'react-router-dom';

const NAV_ITEMS = [
  { path: '/', label: 'Jobs' },
  { path: '/stats', label: 'Stats' },
  { path: '/salary', label: 'Salary' },
  { path: '/trends', label: 'Trends' },
];

export default function Layout() {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-4 py-3">
        <div className="max-w-6xl mx-auto flex items-center gap-6">
          <span className="text-lg font-bold text-gray-900">SWE Jobs</span>
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`text-sm ${
                location.pathname === item.path
                  ? 'text-blue-600 font-medium'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {item.label}
            </Link>
          ))}
        </div>
      </nav>
      <main className="max-w-6xl mx-auto p-4">
        <Outlet />
      </main>
    </div>
  );
}
