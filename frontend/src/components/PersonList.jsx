import styles from './PersonList.module.css';

const TRAJECTORY_OPTIONS = [
  { value: 'all',       label: 'All directions' },
  { value: 'ascending', label: '↑ Ascending'    },
  { value: 'stable',    label: '→ Stable'       },
  { value: 'declining', label: '↓ Declining'    },
];
const SORT_OPTIONS = [
  { value: 'score',      label: 'Relevance'       },
  { value: 'name',       label: 'Name'            },
  { value: 'alignment',  label: 'Alignment index' },
  { value: 'trajectory', label: 'Trajectory'      },
];

function directionOf(vec) {
  if (vec == null) return 'stable';
  if (vec >= 0.3)  return 'ascending';
  if (vec <= -0.3) return 'declining';
  return 'stable';
}
const ARROW = { ascending: '↑', stable: '→', declining: '↓' };

function Initials({ name }) {
  const words = (name || '?').trim().split(/\s+/);
  const text = words.length >= 2
    ? words[0][0] + words[words.length - 1][0]
    : (name || '?')[0];
  return <div className={styles.avatar}>{text.toUpperCase()}</div>;
}

function PersonRow({ hit, selected, onClick }) {
  const { name, headline, direction_vector, alignment_index } = hit.payload ?? {};
  const dir = directionOf(direction_vector);

  return (
    <button
      className={`${styles.row} ${selected ? styles.rowSelected : ''}`}
      onClick={onClick}
    >
      <Initials name={name} />
      <div className={styles.rowBody}>
        <div className={styles.rowName}>{name || hit.payload?.canonical_id || '—'}</div>
        <div className={styles.rowHeadline}>{headline || <span className={styles.dim}>no headline</span>}</div>
      </div>
      <div className={styles.rowMeta}>
        <span className={`badge badge-${dir}`}>{ARROW[dir]}</span>
        {alignment_index != null && (
          <span className={styles.alignScore}>{(alignment_index * 100).toFixed(0)}%</span>
        )}
      </div>
    </button>
  );
}

export default function PersonList({
  query, onQueryChange,
  filters, onFiltersChange,
  sortBy, onSortChange,
  hits, loading, error,
  selectedId, onSelect,
}) {
  const [filtersOpen, setFiltersOpen] = useState(false);

  return (
    <aside className={styles.panel}>
      {/* Search */}
      <div className={styles.searchWrap}>
        <span className={styles.searchIcon}>⌕</span>
        <input
          className={styles.searchInput}
          type="text"
          placeholder="Search people…"
          value={query}
          onChange={e => onQueryChange(e.target.value)}
          spellCheck={false}
        />
        {query && (
          <button className={styles.clearBtn} onClick={() => onQueryChange('')}>✕</button>
        )}
      </div>

      {/* Filter toggle */}
      <div className={styles.filterRow}>
        <button
          className={`${styles.filterToggle} ${filtersOpen ? styles.filterToggleOpen : ''}`}
          onClick={() => setFiltersOpen(v => !v)}
        >
          ⧩ Filters
        </button>
        <select
          className={styles.sortSelect}
          value={sortBy}
          onChange={e => onSortChange(e.target.value)}
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {/* Filter panel */}
      {filtersOpen && (
        <div className={styles.filterPanel}>
          <label className={styles.filterLabel}>Trajectory</label>
          <select
            className={styles.filterSelect}
            value={filters.trajectory}
            onChange={e => onFiltersChange(f => ({ ...f, trajectory: e.target.value }))}
          >
            {TRAJECTORY_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <label className={styles.filterLabel}>Alignment index</label>
          <div className={styles.rangeRow}>
            <span className={styles.rangeVal}>{Math.round(filters.alignMin * 100)}%</span>
            <input
              type="range" min="0" max="1" step="0.05"
              value={filters.alignMin}
              onChange={e => onFiltersChange(f => ({ ...f, alignMin: +e.target.value }))}
              className={styles.range}
            />
            <span className={styles.rangeVal}>{Math.round(filters.alignMax * 100)}%</span>
            <input
              type="range" min="0" max="1" step="0.05"
              value={filters.alignMax}
              onChange={e => onFiltersChange(f => ({ ...f, alignMax: +e.target.value }))}
              className={styles.range}
            />
          </div>

          <button
            className={styles.resetBtn}
            onClick={() => onFiltersChange({ trajectory: 'all', alignMin: 0, alignMax: 1 })}
          >
            Reset filters
          </button>
        </div>
      )}

      {/* Divider + count */}
      <div className={styles.listHeader}>
        <span className={styles.listCount}>
          {loading ? 'searching…' : `${hits.length} person${hits.length !== 1 ? 's' : ''}`}
        </span>
      </div>

      {/* List */}
      <div className={styles.list}>
        {loading && hits.length === 0 && <div className={styles.centred}><div className="spinner" /></div>}
        {error  && <div className={styles.errorMsg}>{error}</div>}
        {!loading && !error && hits.length === 0 && (
          <div className="empty-state">
            <div className="empty-state__icon">∅</div>
            <div className="empty-state__text">No results</div>
          </div>
        )}
        {hits.map(hit => (
          <PersonRow
            key={hit.entity_id}
            hit={hit}
            selected={hit.payload?.canonical_id === selectedId}
            onClick={() => onSelect(hit.payload?.canonical_id ?? hit.entity_id)}
          />
        ))}
      </div>
    </aside>
  );
}

// useState pulled up into file scope to keep JSX clean
import { useState } from 'react';
