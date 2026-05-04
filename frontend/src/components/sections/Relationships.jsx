import { useState, useEffect } from 'react';
import { getRelationships } from '../../api/client.js';
import styles from './sections.module.css';

const KIND_LABELS = {
  worked_at: 'Worked together',
  invested_in: 'Investor',
  'co-founder': 'Co-founder',
  advisor: 'Advisor',
  mentor: 'Mentor',
};

function StrengthBar({ value }) {
  const pct = Math.round((value ?? 0) * 100);
  const color = pct > 70 ? 'var(--green)' : pct > 40 ? 'var(--accent)' : 'var(--text-muted)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div className="bar-bg" style={{ flex: 1 }}>
        <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className={styles.strengthVal}>{pct}%</span>
    </div>
  );
}

export default function Relationships({ entityId }) {
  const [rels, setRels]     = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState(null);

  useEffect(() => {
    if (!entityId) return;
    setLoading(true);
    getRelationships(entityId)
      .then(data => setRels(Array.isArray(data) ? data : []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [entityId]);

  if (!entityId) return <div className={styles.empty}>Entity ID not available.</div>;
  if (loading)   return <div className={styles.centred}><div className="spinner" /></div>;
  if (error)     return <div className={styles.errorMsg}>{error}</div>;
  if (!rels?.length) return <div className={styles.empty}>No relationships recorded yet.</div>;

  return (
    <div className={styles.relList}>
      {rels.map(r => (
        <div key={r.id} className={styles.relItem}>
          <div className={styles.relKind}>
            {KIND_LABELS[r.kind] ?? r.kind ?? 'Connected'}
          </div>
          <div className={styles.relId}>
            {r.from_entity_id === entityId ? r.to_entity_id : r.from_entity_id}
          </div>
          {r.strength != null && <StrengthBar value={r.strength} />}
        </div>
      ))}
    </div>
  );
}
