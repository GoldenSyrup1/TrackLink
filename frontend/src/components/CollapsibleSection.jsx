import { useState } from 'react';
import styles from './CollapsibleSection.module.css';

export default function CollapsibleSection({ title, icon, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={styles.section}>
      <button className={styles.header} onClick={() => setOpen(v => !v)}>
        <span className={styles.icon}>{icon}</span>
        <span className={styles.title}>{title}</span>
        <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}>›</span>
      </button>
      {open && <div className={styles.body}>{children}</div>}
    </div>
  );
}
