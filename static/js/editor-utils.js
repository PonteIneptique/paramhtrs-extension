// ── Selector helpers ──────────────────────────────────────────────────────────
export function getSelector(annot, type) {
  return (annot?.target?.selector || []).find(s => s.type === type) || {};
}
export function getStart(annot)  { return getSelector(annot, 'TextPositionSelector').start ?? 0; }
export function getEnd(annot)    { return getSelector(annot, 'TextPositionSelector').end   ?? 0; }
export function getExact(annot)  { return getSelector(annot, 'TextQuoteSelector').exact  ?? ''; }
export function getPrefix(annot) { return getSelector(annot, 'TextQuoteSelector').prefix ?? ''; }
export function getSuffix(annot) { return getSelector(annot, 'TextQuoteSelector').suffix ?? ''; }
export function getBodyValue(annot) { return annot?.body?.[0]?.value ?? ''; }

// ── Annotation type predicates ────────────────────────────────────────────────
export function isInsertion(annot) {
  return annot?.body?.[0]?.purpose === 'insertion' || getStart(annot) === getEnd(annot);
}
export function isAtrNoise(annot)      { return annot?.body?.[0]?.purpose === 'atr_noise'; }
export function isNonResolvAbbr(annot) { return annot?.body?.[0]?.purpose === 'non_resolv_abbr'; }
export function getNonResolvReason(annot) { return annot?.body?.[0]?.reason ?? 'other'; }
export function getSemtag(annot) { return annot?.body?.[0]?.semtag ?? null; }

export const SEMTAG_LABELS = {
  persName:  'Person',
  orgName:   'Organisation',
  placeName: 'Place',
  num:       'Numeral',
};
export function isSpaceExact(annot) {
  return !isInsertion(annot) && !isAtrNoise(annot) && !isNonResolvAbbr(annot) && getExact(annot).trim() === '';
}

// ── HTML escaping ─────────────────────────────────────────────────────────────
export function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Text transformation ───────────────────────────────────────────────────────
export function applyAnnotations(text, annotations) {
  if (!annotations?.length) return text;
  // Sort right-to-left; for equal start, process larger-end first so that
  // deletions/substitutions are applied before same-start insertions (end===start).
  const sorted = [...annotations].sort((a, b) => {
    const ds = getStart(b) - getStart(a);
    return ds !== 0 ? ds : getEnd(b) - getEnd(a);
  });
  let result = text;
  for (const a of sorted) {
    const s = getStart(a), e = getEnd(a);
    result = result.slice(0, s) + getBodyValue(a) + result.slice(e);
  }
  return result;
}

// ── Source panel HTML ─────────────────────────────────────────────────────────
export function buildSourceHtml(fullText, annotsSorted, selectedAnnotationId) {
  const text  = fullText;
  const selId = selectedAnnotationId;
  // Insertions (zero-width) at the same start as a regular annotation must be
  // rendered first so the ∅ marker visually precedes the annotated span.
  const annots = [...annotsSorted].sort((a, b) => {
    const ds = getStart(a) - getStart(b);
    if (ds !== 0) return ds;
    return (getStart(a) === getEnd(a) ? 0 : 1) - (getStart(b) === getEnd(b) ? 0 : 1);
  });
  let html   = '';
  let cursor = 0;

  for (const a of annots) {
    const s = getStart(a), e = getEnd(a);
    const renderFrom = Math.max(s, cursor);

    if (s > cursor) html += escapeHtml(text.slice(cursor, s));

    const cls = ['r6o-annotation',
      selId === a.id     ? 'selected'           : '',
      a.validated_by     ? 'r6o-validated'      : '',
      isInsertion(a)     ? 'r6o-insertion'      : '',
      isAtrNoise(a)      ? 'r6o-atr-noise'      : '',
      isNonResolvAbbr(a) ? 'r6o-nonresolv-abbr' : '',
    ].filter(Boolean).join(' ');

    if (s === e) {
      html += `<mark class="${cls}" data-annotation="${escapeHtml(a.id)}"></mark>`;
    } else if (renderFrom < e) {
      html += `<mark class="${cls}" data-annotation="${escapeHtml(a.id)}">${escapeHtml(text.slice(renderFrom, e))}</mark>`;
    }
    cursor = Math.max(cursor, e);
  }

  if (cursor < text.length) html += escapeHtml(text.slice(cursor));
  return html;
}

// ── Normalized panel position map ─────────────────────────────────────────────
export function computeNormalizedPositions(annotations) {
  // Sort ascending by start. For the same start position, zero-width insertions
  // must come FIRST so their +1 delta is accumulated before the following
  // substitution's normalised position is computed.
  const ordered = [...annotations].sort((a, b) => {
    const ds = getStart(a) - getStart(b);
    if (ds !== 0) return ds;
    const aZero = getStart(a) === getEnd(a) ? 0 : 1;
    const bZero = getStart(b) === getEnd(b) ? 0 : 1;
    return aZero - bZero;
  });
  const map = {}; let delta = 0;
  for (const a of ordered) {
    const s = getStart(a), e = getEnd(a), val = getBodyValue(a);
    const ns = s + delta;
    map[a.id] = { start: ns, end: ns + val.length };
    delta += val.length - (e - s);
  }
  return map;
}

// ── Normalized panel HTML ─────────────────────────────────────────────────────
export function buildNormalizedPageHtml(normalizedText, annotsSorted, selectedAnnotationId, normalizedPositions) {
  const text      = normalizedText;
  const selId     = selectedAnnotationId;
  const positions = normalizedPositions;

  const annots = annotsSorted
    .map(a => ({ a, pos: positions[a.id] }))
    .filter(({ pos }) => pos && pos.start < pos.end)
    .sort((x, y) => x.pos.start - y.pos.start);

  let html = '', cursor = 0;
  for (const { a, pos } of annots) {
    if (pos.start < cursor) continue;
    if (pos.start > cursor) html += escapeHtml(text.slice(cursor, pos.start));
    const cls = ['norm-annot',
      a.id === selId     ? 'norm-highlight'     : '',
      a.validated_by     ? 'norm-validated'     : '',
      isAtrNoise(a)      ? 'norm-atr-noise'     : '',
      isNonResolvAbbr(a) ? 'norm-nonresolv-abbr': '',
    ].filter(Boolean).join(' ');
    html += `<mark class="${cls}" data-annotation="${escapeHtml(a.id)}">${escapeHtml(text.slice(pos.start, pos.end))}</mark>`;
    cursor = pos.end;
  }
  if (cursor < text.length) html += escapeHtml(text.slice(cursor));
  return html;
}

// ── Mass-cleanup predicates ───────────────────────────────────────────────────

// Space insertion: insertion whose body value is empty or whitespace only
export function isSpaceInsertion(annot) {
  return isInsertion(annot) && !getBodyValue(annot).trim();
}

const PUNCT_START_RE = /^[\p{P}\p{S}]/u;

// Space inserted immediately before a punctuation character
export function isSpaceBeforePunct(annot) {
  if (!isSpaceInsertion(annot)) return false;
  const suffix = getSuffix(annot);
  return !!suffix && PUNCT_START_RE.test(suffix[0]);
}

// Space inserted immediately before another space (would create a double space)
export function isSpaceBeforeSpace(annot) {
  if (!isSpaceInsertion(annot)) return false;
  const suffix = getSuffix(annot);
  return !!suffix && suffix[0] === ' ';
}

// Punctuation annotation:
//   - insertion whose value consists only of Unicode punctuation/symbols (no whitespace)
//   - OR substitution where BOTH exact AND value consist only of punctuation
// Space insertions are handled by isSpaceInsertion and are excluded here.
const PUNCT_RE = /^[\p{P}\p{S}]+$/u;
export function isPunctuationAnnotation(annot) {
  if (isAtrNoise(annot) || isNonResolvAbbr(annot)) return false;
  if (isSpaceInsertion(annot)) return false;
  const val = getBodyValue(annot);
  const ext = getExact(annot);
  if (isInsertion(annot)) return !!val && PUNCT_RE.test(val);
  if (!ext || !val) return false;
  // punct→punct change, or token (pure letters) mapped to punctuation only
  return PUNCT_RE.test(val) && (PUNCT_RE.test(ext) || ALPHA_ONLY_RE.test(ext));
}

// Surnormalization: both exact and value consist entirely of [a-zA-Z] characters
// (no accents, no punctuation, no spaces) — the source was already in clean Latin
// script, making the annotation an over-normalization (e.g. "lui" → "li",
// "quelle" → "quel"). Ramist modifications (u/i ↔ v/j) are explicitly excluded.
const ALPHA_ONLY_RE = /^[a-zA-Z]+$/;
export function isSurnormalization(annot) {
  if (isInsertion(annot) || isAtrNoise(annot) || isNonResolvAbbr(annot)) return false;
  const exact = getExact(annot);
  const value = getBodyValue(annot);
  if (!exact || !value) return false;
  if (!ALPHA_ONLY_RE.test(exact) || !ALPHA_ONLY_RE.test(value)) return false;
  // Capitalisation of the first letter only (e.g. "dieu" → "Dieu") is valid
  if (exact.slice(1) === value.slice(1) && exact[0].toLowerCase() === value[0].toLowerCase()) return false;
  const eL = exact.toLowerCase(), vL = value.toLowerCase();
  const ramist_uv = (eL.includes('u') && vL.includes('v')) || (eL.includes('v') && vL.includes('u'));
  const ramist_ij = (eL.includes('i') && vL.includes('j')) || (eL.includes('j') && vL.includes('i'));
  if (ramist_uv || ramist_ij) return false;
  return true;
}

// ── Bulk validation: find similar unvalidated annotations ─────────────────────
export function findSimilarAnnotations(annotations, targetAnnot) {
  const srcExact = getExact(targetAnnot);
  const tgtValue = getBodyValue(targetAnnot);
  return annotations.filter(a =>
    !a.validated_by && a.id !== targetAnnot.id &&
    getExact(a) === srcExact && getBodyValue(a) === tgtValue
  );
}

// ── Bulk deletion: find unvalidated annotations with same exact text ──────────
// For insertions (start===end), matches by body value instead of exact text.
// Returns [] for space insertions/removals — those are too generic to bulk-delete.
export function findSimilarByExact(annotations, annot) {
  if (isInsertion(annot)) {
    const value = getBodyValue(annot);
    if (!value?.trim()) return [];
    return annotations.filter(a =>
      a.id !== annot.id &&
      !a.validated_by &&
      isInsertion(a) &&
      getBodyValue(a) === value
    );
  }
  if (isSpaceExact(annot)) return [];
  const exact = getExact(annot);
  return annotations.filter(a =>
    a.id !== annot.id &&
    !a.validated_by &&
    !isInsertion(a) &&
    !isAtrNoise(a) &&
    !isNonResolvAbbr(a) &&
    getExact(a) === exact
  );
}

// ── Overlap resolution ────────────────────────────────────────────────────────
// Returns adjusted {start, end} that avoids overlapping any existing annotation,
// or null if the entire proposed span is covered by an existing annotation.
export function resolveAnnotationBounds(start, end, existingAnnotations) {
  const sorted = [...existingAnnotations]
    .filter(a => !isInsertion(a))
    .sort((a, b) => getStart(a) - getStart(b));
  for (const a of sorted) {
    const aStart = getStart(a);
    const aEnd   = getEnd(a);
    if (aEnd <= start || aStart >= end) continue; // no overlap
    if (aStart >= start) {
      end = aStart; // existing starts inside selection: trim our end
    } else {
      start = aEnd; // existing starts before selection: advance our start
    }
    if (start >= end) return null;
  }
  return start < end ? { start, end } : null;
}

// ── Unannotated occurrence finder ─────────────────────────────────────────────
// Returns all {start, end} spans where `exact` appears in `fullText` and is
// not already covered (even partially) by an existing non-insertion annotation.
export function findUnannotatedOccurrences(fullText, exact, annotations) {
  if (!exact || !exact.trim()) return [];
  const nonInsert = annotations.filter(a => !isInsertion(a));
  const results = [];
  let idx = 0;
  while (true) {
    const pos = fullText.indexOf(exact, idx);
    if (pos === -1) break;
    const start = pos, end = pos + exact.length;
    const overlaps = nonInsert.some(a => getStart(a) < end && getEnd(a) > start);
    if (!overlaps) results.push({ start, end });
    idx = pos + 1;
  }
  return results;
}
