import { useState } from 'react';
import styles from './sections.module.css';

export default function RawSignals({ sources }) {
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(sources ?? {}, null, 2);

  async function copy() {
    await navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div>
      <div className={styles.rawHeader}>
        <span className={styles.fieldLabel}>sources JSONB dump</span>
        <button className={styles.copyBtn} onClick={copy}>
          {copied ? '✓ copied' : '⎘ copy'}
        </button>
      </div>
      <pre className={styles.rawPre}>{json}</pre>
    </div>
  );
}
