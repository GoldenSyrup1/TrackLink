import CollapsibleSection from './CollapsibleSection.jsx';
import WorkHistory         from './sections/WorkHistory.jsx';
import SocialActivity      from './sections/SocialActivity.jsx';
import GitHubSignals       from './sections/GitHubSignals.jsx';
import Relationships       from './sections/Relationships.jsx';
import TrajectoryBreakdown from './sections/TrajectoryBreakdown.jsx';
import RawSignals          from './sections/RawSignals.jsx';
import styles from './PersonProfile.module.css';

function directionOf(vec) {
  if (vec == null) return 'stable';
  if (vec >= 0.3)  return 'ascending';
  if (vec <= -0.3) return 'declining';
  return 'stable';
}
const DIR_ARROW = { ascending: '↑', stable: '→', declining: '↓' };

function AlignBar({ value }) {
  const pct = Math.round((value ?? 0) * 100);
  const color = pct > 70 ? 'var(--green)' : pct > 40 ? 'var(--accent)' : 'var(--text-muted)';
  return (
    <div className={styles.alignBar}>
      <div className="bar-bg" style={{ flex: 1 }}>
        <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className={styles.alignVal}>{pct}%</span>
    </div>
  );
}

function timeAgo(isoStr) {
  if (!isoStr) return null;
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins  = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days  = Math.floor(diff / 86400000);
  if (mins < 60)   return `${mins}m ago`;
  if (hours < 24)  return `${hours}h ago`;
  return `${days}d ago`;
}

function ProfileSkeleton() {
  return (
    <div className={styles.skeleton}>
      <div className={styles.skeletonHeader}>
        <div className={`${styles.skeletonBlock} ${styles.skeletonAvatar}`} />
        <div className={styles.skeletonLines}>
          <div className={`${styles.skeletonBlock} ${styles.skeletonName}`} />
          <div className={`${styles.skeletonBlock} ${styles.skeletonSub}`} />
        </div>
      </div>
      {[80, 60, 90, 50].map((w, i) => (
        <div key={i} className={`${styles.skeletonBlock} ${styles.skeletonLine}`} style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

export default function PersonProfile({ canonicalId, card, score, loading, onClose }) {
  if (loading) return <ProfileSkeleton />;

  if (card?._error) {
    return (
      <div className={styles.errorState}>
        <div className={styles.errorIcon}>⚠</div>
        <div>{card._error}</div>
        <button className={styles.closeBtn} onClick={onClose}>← back</button>
      </div>
    );
  }

  if (!card) return null;

  const dir   = directionOf(card.direction_vector);
  const scraped = timeAgo(card.scraped_at);
  const summary = card.sources?.linkedin?.summary;
  const sources = card.sources ?? {};

  return (
    <div className={styles.profile}>
      {/* ── Header ──────────────────────────────────────────── */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <div className={styles.avatarLg}>
            {(card.name ?? '?').trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase()}
          </div>
          <div>
            <h1 className={styles.name}>{card.name ?? canonicalId}</h1>
            <div className={styles.headline}>{card.headline ?? <span className={styles.dim}>no headline</span>}</div>
            {card.sources?.linkedin?.location && (
              <div className={styles.location}>⌖ {card.sources.linkedin.location}</div>
            )}
          </div>
        </div>

        <div className={styles.headerRight}>
          <span className={`badge badge-${dir}`}>
            {DIR_ARROW[dir]} {dir}
          </span>
          <div className={styles.alignGroup}>
            <span className={styles.alignLabel}>alignment</span>
            <AlignBar value={card.alignment_index} />
          </div>
          {scraped && <span className={styles.scraped}>scraped {scraped}</span>}
          <button className={styles.closeBtn} onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      {/* ── Summary blurb ───────────────────────────────────── */}
      {summary && (
        <div className={styles.summary}>
          <p>{summary}</p>
        </div>
      )}

      {/* ── Collapsible sections ─────────────────────────────── */}
      <div className={styles.sections}>
        <CollapsibleSection title="Work history"          icon="◫">
          <WorkHistory sources={sources} />
        </CollapsibleSection>

        <CollapsibleSection title="Social activity"       icon="◈">
          <SocialActivity sources={sources} />
        </CollapsibleSection>

        <CollapsibleSection title="GitHub signals"        icon="⎇">
          <GitHubSignals sources={sources} />
        </CollapsibleSection>

        <CollapsibleSection title="Relationships"         icon="⬡">
          <Relationships entityId={card.id} />
        </CollapsibleSection>

        <CollapsibleSection title="Trajectory breakdown"  icon="⟋">
          <TrajectoryBreakdown card={card} score={score} />
        </CollapsibleSection>

        <CollapsibleSection title="Raw signals"           icon="⧉">
          <RawSignals sources={sources} />
        </CollapsibleSection>
      </div>
    </div>
  );
}
