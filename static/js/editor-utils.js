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
  const text   = fullText;
  const annots = annotsSorted;
  const selId  = selectedAnnotationId;
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
