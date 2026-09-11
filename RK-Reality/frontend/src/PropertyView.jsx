import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Save, FileText } from 'lucide-react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

export default function PropertyView() {
  const { entry_no } = useParams();
  const [prop, setProp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  
  // Form state
  const [formData, setFormData] = useState({});

  useEffect(() => {
    axios.get(`${API_BASE}/properties/${entry_no}`).then((res) => {
      setProp(res.data);
      setFormData({
        owner_full_name: res.data.owner_full_name || '',
        address: res.data.address || '',
        r_number: res.data.r_number || '',
        original_loan_amount: res.data.original_loan_amount || '',
      });
      setLoading(false);
    });
  }, [entry_no]);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await axios.put(`${API_BASE}/properties/${entry_no}`, formData);
      alert('Saved successfully!');
    } catch (e) {
      alert('Failed to save.');
    }
    setSaving(false);
  };

  if (loading) return <p>Loading property details...</p>;

  const pdfUrl = `${API_BASE}/documents/${prop.month}/${entry_no}/trustee_notice.pdf`;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <Link to="/" className="button outline" style={{ padding: '0.5rem' }}>
          <ArrowLeft size={18} />
        </Link>
        <h2 style={{ margin: 0 }}>Property Entry #{entry_no}</h2>
        <span className="badge">{prop.status}</span>
      </div>

      <div className="layout-split">
        {/* Left Panel: PDF Viewer */}
        <div className="panel">
          <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={18} /> Trustee Notice Document
          </div>
          <iframe 
            src={pdfUrl} 
            className="pdf-viewer"
            title="PDF Viewer"
          />
        </div>

        {/* Right Panel: Extracted Data / Editor */}
        <div className="panel">
          <div className="panel-header">
            Validate Extracted Data
          </div>
          <div className="panel-content">
            <div className="form-group">
              <label>Owner Full Name</label>
              <input 
                name="owner_full_name" 
                value={formData.owner_full_name} 
                onChange={handleChange} 
              />
            </div>
            
            <div className="form-group">
              <label>Address</label>
              <input 
                name="address" 
                value={formData.address} 
                onChange={handleChange} 
              />
            </div>
            
            <div className="form-group">
              <label>R-Number (WCAD)</label>
              <input 
                name="r_number" 
                value={formData.r_number} 
                onChange={handleChange} 
              />
            </div>

            <div className="form-group">
              <label>Original Loan Amount</label>
              <input 
                name="original_loan_amount" 
                type="number"
                value={formData.original_loan_amount} 
                onChange={handleChange} 
              />
            </div>

            <button 
              className="button" 
              style={{ marginTop: '1rem', width: '100%', justifyContent: 'center' }}
              onClick={handleSave}
              disabled={saving}
            >
              <Save size={18} /> {saving ? 'Saving...' : 'Save Validation'}
            </button>

            <div style={{ marginTop: '2rem' }}>
              <h4 style={{ color: 'var(--text-muted)' }}>Raw Extraction Logs (JSON)</h4>
              <pre style={{ 
                background: 'rgba(0,0,0,0.3)', 
                padding: '1rem', 
                borderRadius: '8px',
                fontSize: '0.8rem',
                overflowX: 'auto'
              }}>
                {JSON.stringify(prop.steps, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
