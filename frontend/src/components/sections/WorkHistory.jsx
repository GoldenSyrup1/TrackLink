import styles from './sections.module.css';

function yearRange(start, end) {
  if (!start && !end) return '';
  const s = start ?? '?';
  const e = end   ?? 'present';
  return `${s} — ${e}`;
}

export default function WorkHistory({ sources }) {
  const work = sources?.linkedin?.work_history ?? [];

  if (!work.length) {
    return <div className={styles.empty}>No work history in sources.</div>;
  }

  return (
    <div className={styles.timeline}>
      {work.map((w, i) => (
        <div key={i} className={styles.timelineItem}>
          <div className={styles.timelineDot} />
          {i < work.length - 1 && <div className={styles.timelineLine} />}
          <div className={styles.timelineContent}>
            <div className={styles.timelineTitle}>{w.title || '—'}</div>
            <div className={styles.timelineCompany}>{w.company || '—'}</div>
            <div className={styles.timelineDates}>{yearRange(w.start_year, w.end_year)}</div>
            {w.description && (
              <div className={styles.timelineDesc}>{w.description}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
