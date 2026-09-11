import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Save, FileText, BarChart3, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

const API = '/api';

function fmt$(v) { return v != null ? `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—'; }
function fmtPct(v) { return v != null ? `${(v * 100).toFixed(1)}%` : '—'; }
function fmtRate(v) { return v != null ? `${(v * 100).toFixed(2)}%` : '—'; }

export default function PropertyDetail() {
  const { entry_no } = useParams();
  const navigate = useNavigate();
  const [prop, setProp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null); // { type: 'success'|'error', text: string }
  const [form, setForm] = useState({});
  const [pdfUrl, setPdfUrl] = useState('');

  useEffect(() => {
    const decoded = decodeURIComponent(entry_no);
    axios.get(`${API}/properties/${decoded}`).then(r => {
      const d = r.data;
      setProp(d);
      setForm({
        owner_full_name: d.owner_full_name || '',
        address: d.address || '',
        r_number: d.r_number || '',
        original_loan_amount: d.original_loan_amount || '',
      });
      if (d.month) {
        setPdfUrl(`${API}/documents/${d.month}/${decoded}/trustee_notice.pdf`);
      }
      setLoading(false);
    });
  }, [entry_no]);

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      await axios.put(`${API}/properties/${decodeURIComponent(entry_no)}`, form);
      setProp(p => ({ ...p, ...form }));
      setSaveMsg({ type: 'success', text: 'Saved successfully! Data updated in database.' });
    } catch { setSaveMsg({ type: 'error', text: 'Save failed — check backend connection.' }); }
    setSaving(false);
  };

  if (loading) return <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>Loading...</div>;
  if (!prop) return <div style={{ padding: '2rem', color: 'var(--danger)' }}>Property not found.</div>;

  const le = prop.loan_estimate;
  const flagColor = {
    GOOD_CANDIDATE: 'var(--success)',
    LOW_PAYDOWN: 'var(--warning)',
    NO_DATA: 'var(--text-muted)',
  }[le?.filter_flag] || 'var(--text-muted)';

  return (
    <div style={{ height: '100%' }}>
      {/* Back bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.25rem' }}>
        <button className="btn btn-outline btn-sm" onClick={() => navigate(-1)}>
          <ArrowLeft size={16} /> Back
        </button>
        <div>
          <h1 className="page-title" style={{ fontSize: '1.15rem', margin: 0 }}>
            {prop.source_file_name || prop.entry_no}
          </h1>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            {prop.month} · {prop.county}
          </div>
        </div>
        {le?.filter_flag && (
          <span style={{ marginLeft: 'auto', color: flagColor, fontWeight: 700, fontSize: '0.9rem' }}>
            {le.filter_flag === 'GOOD_CANDIDATE' ? '✅' : '⚠'} {le.filter_flag.replace('_', ' ')}
          </span>
        )}
      </div>

      <div className="detail-layout">
        {/* Left: PDF + Data Presentation */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', overflow: 'auto' }}>
          {/* Amortization Summary */}
          {le && (
            <div className="panel" style={{ flexShrink: 0 }}>
              <div className="panel-header"><BarChart3 size={16} /> Financial Analysis</div>
              <div style={{ padding: '1rem' }}>
                <div className="amort-grid">
                  <div className="amort-item">
                    <div className="v">{fmt$(prop.original_loan_amount)}</div>
                    <div className="k">Original Loan</div>
                  </div>
                  <div className="amort-item">
                    <div className="v" style={{ color: 'var(--warning)' }}>{fmt$(le.est_remaining_balance)}</div>
                    <div className="k">Est. Remaining Balance</div>
                  </div>
                  <div className="amort-item">
                    <div className="v" style={{ color: 'var(--success)' }}>{fmt$(le.est_principal_paid)}</div>
                    <div className="k">Principal Paid</div>
                  </div>
                  <div className="amort-item">
                    <div className="v">{fmtPct(le.est_pct_paid_down)}</div>
                    <div className="k">% Paid Down</div>
                  </div>
                  <div className="amort-item">
                    <div className="v">{fmtRate(le.assumed_rate)}</div>
                    <div className="k">Assumed Rate</div>
                  </div>
                  <div className="amort-item">
                    <div className="v">{le.months_elapsed ?? '—'} mo</div>
                    <div className="k">Months Elapsed</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* All Property Fields */}
          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-header"><FileText size={16} /> Property Data — Read View</div>
            <div className="panel-body">
              <div className="field-grid">
                {[
                  ['Entry No', prop.entry_no],
                  ['File Name', prop.source_file_name],
                  ['Sale Date', prop.sale_date],
                  ['Instrument No', prop.instrument_number],
                  ['Is Purchase Money', prop.is_purchase_money == null ? '—' : prop.is_purchase_money ? 'Yes' : 'No'],
                  ['Has HOA Rider', prop.has_hoa_rider == null ? '—' : prop.has_hoa_rider ? 'Yes' : 'No'],
                  ['Loan Type', prop.loan_type],
                  ['Pipeline Status', prop.status],
                ].map(([k, v]) => (
                  <div className="form-field" key={k}>
                    <label>{k}</label>
                    <div className="value-display">{v || '—'}</div>
                  </div>
                ))}
              </div>

              <div className="section-title" style={{ marginTop: '1rem' }}>Lender / Servicer Info</div>
              <div className="form-field field-grid full">
                <div className="form-field">
                  <label>Lender</label>
                  <div className="value-display" style={{ fontSize: '0.8rem', maxHeight: 80, overflow: 'auto' }}>{prop.lender || '—'}</div>
                </div>
                <div className="form-field">
                  <label>Servicer</label>
                  <div className="value-display" style={{ fontSize: '0.8rem', maxHeight: 80, overflow: 'auto' }}>{prop.servicer || '—'}</div>
                </div>
              </div>

              <div className="section-title">Legal Description</div>
              <div className="value-display" style={{ fontSize: '0.8rem', maxHeight: 100, overflow: 'auto' }}>
                {prop.legal_description || '—'}
              </div>
            </div>
          </div>

          {/* PDF Viewer */}
          <div className="panel" style={{ height: 500, flexShrink: 0 }}>
            <div className="panel-header"><FileText size={16} /> Trustee Notice PDF</div>
            {pdfUrl ? (
              <iframe src={pdfUrl} style={{ border: 'none', flex: 1, width: '100%', height: '100%' }} title="PDF" />
            ) : (
              <div style={{ padding: '2rem', color: 'var(--text-muted)', textAlign: 'center' }}>No PDF available</div>
            )}
          </div>
        </div>

        {/* Right: Validation Editor */}
        <div className="panel">
          <div className="panel-header"><Save size={16} /> Validate & Correct Data</div>
          <div className="panel-body">
            <div style={{ background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 8, padding: '0.75rem 1rem', marginBottom: '1.25rem', fontSize: '0.82rem', color: 'var(--warning)' }}>
              <AlertTriangle size={14} style={{ display: 'inline', marginRight: 6 }} />
              Edit any field below and click Save to correct extracted data in the database.
            </div>

            <div className="form-field" style={{ marginBottom: '1rem' }}>
              <label>Owner Full Name</label>
              <input value={form.owner_full_name} onChange={e => setForm({ ...form, owner_full_name: e.target.value })} placeholder="e.g. JOHN DOE AND JANE DOE" />
            </div>

            <div className="form-field" style={{ marginBottom: '1rem' }}>
              <label>Property Address</label>
              <input value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} placeholder="123 Main St, Georgetown, TX 78628" />
            </div>

            <div className="form-field" style={{ marginBottom: '1rem' }}>
              <label>R-Number (WCAD)</label>
              <input value={form.r_number} onChange={e => setForm({ ...form, r_number: e.target.value })} placeholder="R123456" />
            </div>

            <div className="form-field" style={{ marginBottom: '1rem' }}>
              <label>Original Loan Amount</label>
              <input type="number" value={form.original_loan_amount} onChange={e => setForm({ ...form, original_loan_amount: e.target.value })} placeholder="250000" />
            </div>

            <button
              className="btn btn-primary"
              style={{ width: '100%', justifyContent: 'center', marginTop: '0.5rem' }}
              onClick={handleSave}
              disabled={saving}
            >
              <Save size={16} /> {saving ? 'Saving...' : 'Save Validation'}
            </button>
            {saveMsg && (
              <div style={{
                marginTop: '0.75rem', padding: '0.65rem 0.85rem', borderRadius: 8,
                background: saveMsg.type === 'success' ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                border: `1px solid ${saveMsg.type === 'success' ? 'var(--success)' : 'var(--danger)'}`,
                color: saveMsg.type === 'success' ? 'var(--success)' : 'var(--danger)',
                fontSize: '0.85rem',
              }}>
                {saveMsg.type === 'success' ? '✅' : '❌'} {saveMsg.text}
              </div>
            )}

            {/* Raw OCR dumps */}
            {prop.steps && Object.keys(prop.steps).length > 0 && (
              <>
                <div className="section-title">Raw OCR / Extraction Logs</div>
                {Object.entries(prop.steps).map(([step, json]) => (
                  <details key={step} style={{ marginBottom: '0.5rem' }}>
                    <summary style={{ cursor: 'pointer', fontSize: '0.8rem', color: 'var(--text-muted)', padding: '0.25rem' }}>
                      {step}
                    </summary>
                    <pre style={{ background: 'var(--bg)', borderRadius: 6, padding: '0.75rem', fontSize: '0.72rem', color: '#7ec8a4', overflow: 'auto', maxHeight: 200, margin: '0.25rem 0 0' }}>
                      {json ? JSON.stringify(JSON.parse(json), null, 2) : 'No data'}
                    </pre>
                  </details>
                ))}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
