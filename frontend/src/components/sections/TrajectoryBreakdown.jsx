import styles from './sections.module.css';

function ScoreBar({ label, value, max = 100, color }) {
  const pct = Math.min(100, Math.round((value ?? 0) / max * 100));
  const barColor = color ?? (pct > 70 ? 'var(--green)' : pct > 40 ? 'var(--accent)' : 'var(--text-muted)');
  return (
    <div className={styles.scoreRow}>
      <span className={styles.scoreLabel}>{label}</span>
      <div className="bar-bg" style={{ flex: 1 }}>
        <div className="bar-fill" style={{ width: `${pct}%`, background: barColor }} />
      </div>
      <span className={styles.scoreVal}>{typeof value === 'number' ? value.toFixed(1) : '—'}</span>
    </div>
  );
}

function DirectionArrow({ vec }) {
  if (vec == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  if (vec >= 0.3)  return <span style={{ color: 'var(--green)',  fontSize: 20 }}>↑</span>;
  if (vec <= -0.3) return <span style={{ color: 'var(--red)',    fontSize: 20 }}>↓</span>;
  return             <span style={{ color: 'var(--text-secondary)', fontSize: 20 }}>→</span>;
}

export default function TrajectoryBreakdown({ card, score }) {
  const ts   = card?.trajectory_score   ?? score ?? {};
  const dv   = card?.direction_vector;
  const ai   = card?.alignment_index;

  return (
    <div>
      {/* Direction + alignment */}
      <div className="section-grid" style={{ marginBottom: 20 }}>
        <div className="stat-card">
          <div className="stat-card__label">Direction</div>
          <div className="stat-card__value" style={{ fontSize: 28 }}>
            <DirectionArrow vec={dv} />
          </div>
          <div className="stat-card__sub">
            {dv != null ? dv.toFixed(3) : '—'}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Alignment</div>
          <div className="stat-card__value">
            {ai != null ? `${(ai * 100).toFixed(0)}%` : '—'}
          </div>
          <div className="stat-card__sub">emerging tech overlap</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Composite</div>
          <div className="stat-card__value">
            {ts.composite != null ? ts.composite.toFixed(1) : '—'}
          </div>
          <div className="stat-card__sub">/ 100</div>
        </div>
      </div>

      {/* Sub-scores */}
      <div className={styles.scoreTable}>
        <ScoreBar label="Career momentum"  value={ts.career_momentum} />
        <ScoreBar label="GitHub activity"  value={ts.github_activity} />
        <ScoreBar label="Social reach"     value={ts.social_reach} />
        <ScoreBar label="LLM assessment"   value={ts.llm_score} />
      </div>

      {/* Rationale */}
      {ts.rationale && (
        <div className={styles.rationaleBlock}>
          <span className={styles.fieldLabel}>LLM rationale</span>
          <p className={styles.rationale}>"{ts.rationale}"</p>
        </div>
      )}

      {ts.scored_at && (
        <div className={styles.scoredAt}>
          scored {new Date(ts.scored_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}
