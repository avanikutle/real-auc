import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Building2, DollarSign, User, Hash, ChevronRight, AlertTriangle, CheckCircle2, Clock } from 'lucide-react';

const API = '/api';

const FLAG_BADGE = {
  GOOD_CANDIDATE: ['badge badge-success', '✅ Good Candidate'],
  LOW_PAYDOWN:    ['badge badge-warning', '⚠ Low Paydown'],
  NO_DATA:        ['badge badge-default', '— No Data'],
};

function statusBadge(status) {
  if (status?.includes('step6') || status?.includes('step7')) return <span className="badge badge-success">{status}</span>;
  if (status?.includes('step')) return <span className="badge badge-primary">{status}</span>;
  if (status === 'pending') return <span className="badge badge-warning">pending</span>;
  return <span className="badge badge-default">{status || '—'}</span>;
}

export default function Dashboard({ selectedMonth }) {
  const [props, setProps] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    if (!selectedMonth) return;
    setLoading(true);
    axios.get(`${API}/properties?month=${selectedMonth}`)
      .then(r => { setProps(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedMonth]);

  // Summary stats
  const total = props.length;
  const withOwner = props.filter(p => p.owner_full_name).length;
  const withRNum = props.filter(p => p.r_number).length;
  const goodCandidates = props.filter(p => p.filter_flag === 'GOOD_CANDIDATE').length;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Properties — {selectedMonth}</h1>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="value">{total}</div>
          <div className="label">Total Entries</div>
        </div>
        <div className="stat-card">
          <div className="value" style={{ color: 'var(--success)' }}>{goodCandidates}</div>
          <div className="label">Good Candidates</div>
        </div>
        <div className="stat-card">
          <div className="value" style={{ color: withOwner === total ? 'var(--success)' : 'var(--warning)' }}>{withOwner}</div>
          <div className="label">Owner Name Found</div>
        </div>
        <div className="stat-card">
          <div className="value" style={{ color: withRNum === total ? 'var(--success)' : 'var(--warning)' }}>{withRNum}</div>
          <div className="label">R-Number Found</div>
        </div>
      </div>

      <div className="table-wrap">
        {loading ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>Loading...</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>File / Entry</th>
                <th>Owner</th>
                <th>Address</th>
                <th>R-Number</th>
                <th>Loan Amount</th>
                <th>Origination</th>
                <th>Est. Balance</th>
                <th>% Paid</th>
                <th>Flag</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {props.map((p, i) => {
                const [cls, label] = FLAG_BADGE[p.filter_flag] || ['badge badge-default', p.filter_flag || '—'];
                return (
                  <tr key={p.entry_no} onClick={() => navigate(`/property/${encodeURIComponent(p.entry_no)}`)}>
                    <td className="cell-muted">{i + 1}</td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{p.source_file_name || p.entry_no}</div>
                      <div className="cell-muted">{p.county}</div>
                    </td>
                    <td>
                      {p.owner_full_name
                        ? <span style={{ color: 'var(--text)' }}>{p.owner_full_name}</span>
                        : <span className="cell-muted" style={{ color: 'var(--danger)' }}>⚠ Missing</span>}
                    </td>
                    <td style={{ maxWidth: 200 }}><div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.address || '—'}</div></td>
                    <td>
                      {p.r_number
                        ? <span style={{ fontFamily: 'monospace', color: 'var(--primary)' }}>{p.r_number}</span>
                        : <span className="cell-muted" style={{ color: 'var(--danger)' }}>⚠ Missing</span>}
                    </td>
                    <td>{p.original_loan_amount ? `$${p.original_loan_amount.toLocaleString()}` : '—'}</td>
                    <td className="cell-muted">{p.loan_origination_date || '—'}</td>
                    <td>{p.est_remaining_balance ? `$${Math.round(p.est_remaining_balance).toLocaleString()}` : '—'}</td>
                    <td>{p.est_pct_paid_down != null ? `${(p.est_pct_paid_down * 100).toFixed(1)}%` : '—'}</td>
                    <td><span className={cls}>{label}</span></td>
                    <td>{statusBadge(p.status)}</td>
                    <td><ChevronRight size={16} style={{ color: 'var(--text-muted)' }} /></td>
                  </tr>
                );
              })}
              {props.length === 0 && (
                <tr><td colSpan={12} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                  No properties found. Run the pipeline from Admin → Pipeline.
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
