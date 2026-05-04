import styles from './sections.module.css';

const LANG_COLORS = {
  python: '#3572A5', javascript: '#f1e05a', typescript: '#2b7489',
  rust: '#dea584', go: '#00ADD8', kotlin: '#A97BFF',
  swift: '#F05138', ruby: '#701516', java: '#b07219',
  'c++': '#f34b7d', c: '#555555', haskell: '#5e5086',
};

function LangDot({ lang }) {
  const color = LANG_COLORS[lang.toLowerCase()] ?? '#8b91ae';
  return (
    <span className={styles.langDot} style={{ background: color }} title={lang} />
  );
}

export default function GitHubSignals({ sources }) {
  const gh = sources?.github;

  if (!gh) {
    return <div className={styles.empty}>No GitHub data in sources.</div>;
  }

  return (
    <div>
      <div className="section-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-card__label">Public repos</div>
          <div className="stat-card__value">{gh.public_repos ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Followers</div>
          <div className="stat-card__value">{(gh.followers ?? 0).toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Streak</div>
          <div className="stat-card__value">{gh.contribution_streak ?? 0}</div>
          <div className="stat-card__sub">active days</div>
        </div>
      </div>

      {gh.top_languages?.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className={styles.fieldLabel} style={{ marginBottom: 8 }}>Languages</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {gh.top_languages.map((lang, i) => (
              <span key={i} className="tag" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <LangDot lang={lang} />
                {lang}
              </span>
            ))}
          </div>
        </div>
      )}

      {gh.recent_push_repos?.length > 0 && (
        <div>
          <div className={styles.fieldLabel} style={{ marginBottom: 8 }}>Recent repos</div>
          <div className={styles.repoList}>
            {gh.recent_push_repos.map((r, i) => (
              <div key={i} className={styles.repoItem}>
                <span className={styles.repoIcon}>⌥</span>
                <span className={styles.repoName}>{r}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
