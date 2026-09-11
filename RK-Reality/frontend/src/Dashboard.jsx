import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Download } from 'lucide-react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

export default function Dashboard() {
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API_BASE}/properties`).then((res) => {
      setProperties(res.data);
      setLoading(false);
    });
  }, []);

  const handleExport = async () => {
    try {
      const res = await axios.post(`${API_BASE}/export/step1`);
      alert(`Exported successfully to: ${res.data.path}`);
    } catch (e) {
      alert('Export failed');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h2>Auction Pipeline Dashboard</h2>
        <button className="button" onClick={handleExport}>
          <Download size={18} /> Export Step 1 CSV
        </button>
      </div>

      {loading ? (
        <p>Loading properties...</p>
      ) : (
        <div className="grid">
          {properties.map((p) => (
            <Link to={`/property/${p.entry_no}`} key={p.entry_no} className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <span className="badge">{p.month}</span>
                <span className={`badge ${p.status.includes('done') ? 'success' : ''}`}>
                  {p.status}
                </span>
              </div>
              <h3>{p.address || `Entry #${p.entry_no}`}</h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', margin: '0.5rem 0' }}>
                Owner: {p.owner_full_name || 'Unknown'}
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', margin: 0 }}>
                R-Number: {p.r_number || 'Missing'}
              </p>
            </Link>
          ))}
          {properties.length === 0 && <p>No properties found in DB.</p>}
        </div>
      )}
    </div>
  );
}
