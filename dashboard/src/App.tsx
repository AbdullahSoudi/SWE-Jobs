import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Stats from './pages/Stats';
import Salary from './pages/Salary';
import Trends from './pages/Trends';

export default function App() {
  return (
    <BrowserRouter basename="/SWE-Jobs">
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/salary" element={<Salary />} />
          <Route path="/trends" element={<Trends />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
