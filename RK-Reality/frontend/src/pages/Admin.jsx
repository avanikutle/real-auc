import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Play, RefreshCw, CheckCircle2, AlertCircle, Info } from 'lucide-react';

const API = '/api';

function Toast({ message, type = 'info', onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 8000);
    return () => clearTimeout(t);
  }, []);
  const colors = { info: 'var(--primary)', error: 'var(--danger)', success: 'var(--success)' };
  return (
    <div style={{
      position: 'fixed', bottom: '1.5rem', right: '1.5rem', zIndex: 9999,
      background: 'var(--surface2)', border: `1px solid ${colors[type]}`,
      borderRadius: 10, padding: '0.85rem 1.25rem', maxWidth: 380,
      boxShadow: '0 8px 30px rgba(0,0,0,0.5)', color: 'var(--text)',
      fontSize: '0.875rem', cursor: 'pointer', animation: 'fadeIn 0.2s ease'
    }} onClick={onDismiss}>
      <strong style={{ color: colors[type] }}>{type === 'error' ? '❌ Error' : type === 'success' ? '✅ Done' : 'ℹ️ Info'}</strong>
      <div style={{ marginTop: '0.25rem' }}>{message}</div>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>Click to dismiss</div>
    </div>
  );
}

const STEPS = [
  { step: 0, name: 'Download Notices', desc: 'Fetches trustee-sale PDFs from Williamson County portal' },
  { step: 1, name: 'Parse Notice (OCR)', desc: 'Extracts owner name, address, loan amount from PDFs' },
  { step: 2, name: 'WCAD Lookup', desc: 'Searches Appraisal District for R-Number and property details' },
  { step: 3, name: 'Tax Check', desc: 'Queries county tax records for delinquency' },
  { step: 4, name: 'Deed of Trust', desc: 'Extracts origination date & loan type from DoT' },
  { step: 5, name: 'Lien Check', desc: 'Checks public records for additional liens' },
  { step: 6, name: 'Amortize', desc: 'Estimates remaining balance and flags good candidates' },
  { step: 7, name: 'Export', desc: 'Generates Excel and CSV from pipeline results' },
];

function StepCard({ step, stepDef, month, showToast }) {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const logRef = useRef(null);
  const pollRef = useRef(null);

  const taskId = `step${step}_${month}`;

  const scrollLogs = () => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  };

  useEffect(() => { scrollLogs(); }, [logs]);

  const startPolling = () => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await axios.get(`${API}/pipeline/logs/${taskId}`);
        setLogs(res.data.logs);
        if (!res.data.running) {
          clearInterval(pollRef.current);
          setRunning(false);
          setDone(true);
        }
      } catch (_) {}
    }, 1000);
  };

  const handleRun = async (force = false) => {
    if (!month) {
      setError('⚠ No month selected. Use the sidebar dropdown.');
      return;
    }
    setRunning(true);
    setDone(false);
    setLogs([]);
    setError('');
    try {
      await axios.post(`${API}/pipeline/run-step`, { step, month, force });
      startPolling();
    } catch (e) {
      setLogs([`❌ Request failed: ${e.message}`]);
      setRunning(false);
    }
  };

  useEffect(() => () => clearInterval(pollRef.current), []);

  return (
    <div className="step-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <span style={{ background: 'var(--primary-glow)', color: 'var(--primary)', width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, flexShrink: 0 }}>{step}</span>
            <h3>{stepDef.name}</h3>
            {done && !running && <CheckCircle2 size={16} style={{ color: 'var(--success)' }} />}
          </div>
          <p>{stepDef.desc}</p>
        </div>
      </div>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="btn btn-primary btn-sm" onClick={() => handleRun(false)} disabled={running}>
          {running ? <><RefreshCw size={14} className="spin" /> Running...</> : <><Play size={14} /> Run</>}
        </button>
        <button className="btn btn-outline btn-sm" onClick={() => handleRun(true)} disabled={running}>
          Force Re-run
        </button>
      </div>
      {error && <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)', borderRadius: 6, padding: '0.5rem 0.75rem', marginTop: '0.5rem', fontSize: '0.8rem', color: 'var(--danger)' }}>{error}</div>}
      {logs.length > 0 && (
        <div className="log-box" ref={logRef}>
          {logs.join('')}
        </div>
      )}
    </div>
  );
}

export default function Admin({ selectedMonth }) {
  const [status, setStatus] = useState({});

  useEffect(() => {
    if (!selectedMonth) return;
    axios.get(`${API}/pipeline/status/${selectedMonth}`)
      .then(r => setStatus(r.data))
      .catch(() => {});
  }, [selectedMonth]);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Admin — Pipeline Control</h1>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Month: <strong style={{ color: 'var(--text)' }}>{selectedMonth || 'Select a month'}</strong>
        </div>
      </div>

      {Object.keys(status).length > 0 && (
        <div className="card" style={{ marginBottom: '1.5rem' }}>
          <div className="section-title">Current Pipeline Status</div>
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
            {Object.entries(status).map(([s, count]) => (
              <span key={s} className="badge badge-primary" style={{ fontSize: '0.8rem' }}>
                {s}: <strong>{count}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="steps-grid">
        {STEPS.map(s => (
          <StepCard key={s.step} step={s.step} stepDef={s} month={selectedMonth} />
        ))}
      </div>

      <style>{`.spin { animation: spin 1s linear infinite; } @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
