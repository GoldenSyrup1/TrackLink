import styles from './sections.module.css';

export default function SocialActivity({ sources }) {
  const tw = sources?.twitter;

  if (!tw) {
    return <div className={styles.empty}>No Twitter/X data in sources.</div>;
  }

  return (
    <div>
      <div className="section-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-card__label">Followers</div>
          <div className="stat-card__value">{(tw.followers ?? 0).toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Following</div>
          <div className="stat-card__value">{(tw.following ?? 0).toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Tweets</div>
          <div className="stat-card__value">{(tw.tweet_count ?? 0).toLocaleString()}</div>
        </div>
      </div>

      {tw.bio && (
        <div className={styles.bioBlock}>
          <span className={styles.fieldLabel}>Bio</span>
          <p className={styles.bio}>{tw.bio}</p>
        </div>
      )}

      {tw.recent_topics?.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className={styles.fieldLabel} style={{ marginBottom: 8 }}>Recent topics</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {tw.recent_topics.map((t, i) => (
              <span key={i} className="tag">{t}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
