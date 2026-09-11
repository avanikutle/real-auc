import { useState, useEffect } from 'react';
import { Routes, Route, NavLink } from 'react-router-dom';
import { LayoutDashboard, Settings, Download, Database } from 'lucide-react';
import Dashboard from './pages/Dashboard';
import Admin from './pages/Admin';
import PropertyDetail from './pages/PropertyDetail';
import axios from 'axios';

const API = '/api';

export default function App() {
  const [months, setMonths] = useState([]);
  const [selectedMonth, setSelectedMonth] = useState('');

  useEffect(() => {
    axios.get(`${API}/months`).then(r => {
      setMonths(r.data);
      if (r.data.length > 0) setSelectedMonth(r.data[0]);
    });
  }, []);

  const handleExport = () => {
    const url = selectedMonth
      ? `${API}/export/csv?month=${selectedMonth}`
      : `${API}/export/csv`;
    window.open(url, '_blank');
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <Database size={20} /> RK-<span>Reality</span>
        </div>

        <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <LayoutDashboard size={18} /> Dashboard
        </NavLink>

        <NavLink to="/admin" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <Settings size={18} /> Admin / Pipeline
        </NavLink>

        <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.5rem', fontWeight: 700 }}>
            Month
          </div>
          <select
            value={selectedMonth}
            onChange={e => setSelectedMonth(e.target.value)}
            style={{
              width: '100%',
              marginBottom: '0.75rem',
              background: '#1e3251',
              border: '1px solid var(--primary)',
              color: 'var(--text)',
              padding: '0.6rem 0.75rem',
              borderRadius: '8px',
              fontSize: '0.875rem',
              cursor: 'pointer',
              fontWeight: 600,
              appearance: 'auto',
            }}
          >
            {months.length === 0 && <option value="">Loading...</option>}
            {months.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} onClick={handleExport}>
            <Download size={16} /> Export CSV
          </button>
        </div>
      </aside>

      <main className="main fade-in">
        <Routes>
          <Route path="/" element={<Dashboard selectedMonth={selectedMonth} />} />
          <Route path="/admin" element={<Admin selectedMonth={selectedMonth} />} />
          <Route path="/property/:entry_no" element={<PropertyDetail />} />
        </Routes>
      </main>
    </div>
  );
}
