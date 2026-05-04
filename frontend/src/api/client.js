const BASE = 'http://127.0.0.1:8000';

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

/** POST /search/persons — returns { query, hits: [{entity_id, score, payload}] } */
export async function searchPersons(query, { limit = 40, scoreThreshold = 0.05 } = {}) {
  return req('/search/persons', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: query?.trim() || 'engineer developer founder',
      limit,
      score_threshold: scoreThreshold,
    }),
  });
}

/** GET /persons/{canonical_id} — full person card */
export async function getPerson(canonicalId) {
  return req(`/persons/${encodeURIComponent(canonicalId)}`);
}

/** GET /persons/{canonical_id}/score — trajectory score detail */
export async function getPersonScore(canonicalId) {
  return req(`/persons/${encodeURIComponent(canonicalId)}/score`);
}

/** GET /relationships/?entity_id={uuid} */
export async function getRelationships(entityId, limit = 20) {
  return req(`/relationships/?entity_id=${entityId}&limit=${limit}`);
}
