import { useState, useEffect, useCallback, useRef } from 'react';
import { searchPersons, getPerson, getPersonScore } from './api/client.js';
import PersonList from './components/PersonList.jsx';
import PersonProfile from './components/PersonProfile.jsx';
import styles from './App.module.css';

const DEFAULT_FILTERS = { trajectory: 'all', alignMin: 0, alignMax: 1 };
const DEFAULT_SORT    = 'score';

function directionLabel(vec) {
  if (vec == null) return 'stable';
  if (vec >= 0.3)  return 'ascending';
  if (vec <= -0.3) return 'declining';
  return 'stable';
}

export default function App() {
  const [query,      setQuery]      = useState('');
  const [filters,    setFilters]    = useState(DEFAULT_FILTERS);
  const [sortBy,     setSortBy]     = useState(DEFAULT_SORT);
  const [hits,       setHits]       = useState([]);        // raw search hits
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState(null);

  const [selectedId, setSelectedId] = useState(null);      // canonical_id
  const [card,       setCard]       = useState(null);
  const [score,      setScore]      = useState(null);
  const [cardLoading, setCardLoading] = useState(false);

  const searchRef = useRef(null);

  // ── Search / filter ────────────────────────────────────────
  const runSearch = useCallback(async (q) => {
    setLoading(true);
    setError(null);
    try {
      const data = await searchPersons(q);
      setHits(data.hits ?? []);
    } catch (e) {
      setError(e.message);
      setHits([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounce query changes
  useEffect(() => {
    const t = setTimeout(() => runSearch(query), 300);
    return () => clearTimeout(t);
  }, [query, runSearch]);

  // ── Derived: filtered + sorted list ───────────────────────
  const displayedHits = hits
    .filter(h => {
      const vec = h.payload?.direction_vector ?? null;
      const align = h.payload?.alignment_index ?? null;
      if (filters.trajectory !== 'all' && directionLabel(vec) !== filters.trajectory) return false;
      if (align != null && (align < filters.alignMin || align > filters.alignMax)) return false;
      return true;
    })
    .sort((a, b) => {
      if (sortBy === 'score')      return (b.score ?? 0) - (a.score ?? 0);
      if (sortBy === 'name')       return (a.payload?.name ?? '').localeCompare(b.payload?.name ?? '');
      if (sortBy === 'alignment')  return (b.payload?.alignment_index ?? 0) - (a.payload?.alignment_index ?? 0);
      if (sortBy === 'trajectory') return (b.payload?.direction_vector ?? 0) - (a.payload?.direction_vector ?? 0);
      return 0;
    });

  // ── Load full card when selection changes ──────────────────
  useEffect(() => {
    if (!selectedId) { setCard(null); setScore(null); return; }
    let cancelled = false;
    setCardLoading(true);
    setCard(null);
    setScore(null);

    (async () => {
      try {
        const [c, s] = await Promise.all([
          getPerson(selectedId),
          getPersonScore(selectedId).catch(() => null),
        ]);
        if (!cancelled) { setCard(c); setScore(s); }
      } catch (e) {
        if (!cancelled) setCard({ _error: e.message });
      } finally {
        if (!cancelled) setCardLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [selectedId]);

  return (
    <div className={styles.shell}>
      {/* ── Topbar ─────────────────────────────────────────── */}
      <header className={styles.topbar}>
        <div className={styles.wordmark}>
          <span className={styles.wordmarkDot} />
          TrackLink
        </div>
        <span className={styles.topbarSub}>person intelligence</span>
      </header>

      {/* ── Body ───────────────────────────────────────────── */}
      <div className={styles.body}>
        <PersonList
          query={query}
          onQueryChange={setQuery}
          filters={filters}
          onFiltersChange={setFilters}
          sortBy={sortBy}
          onSortChange={setSortBy}
          hits={displayedHits}
          loading={loading}
          error={error}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />

        <main className={styles.main}>
          {selectedId ? (
            <PersonProfile
              canonicalId={selectedId}
              card={card}
              score={score}
              loading={cardLoading}
              onClose={() => setSelectedId(null)}
            />
          ) : (
            <div className="empty-state">
              <div className="empty-state__icon">◈</div>
              <div className="empty-state__text">
                Select a person from the list to view their profile
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
