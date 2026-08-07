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
export function isMarkup(annot) { return annot?.body?.[0]?.purpose === 'markup'; }
export function getSemtag(annot) { return annot?.body?.[0]?.semtag ?? null; }
export function isGapBefore(annot) { return !!annot?.body?.[0]?.gap_before; }
export function isGapAfter(annot)  { return !!annot?.body?.[0]?.gap_after; }

export const SEMTAG_LABELS = {
  persName:  'Person',
  orgName:   'Organisation',
  placeName: 'Place',
  num:       'Numeral',
};
export const SEMTAG_ABBREVS = {
  persName:  'per',
  orgName:   'org',
  placeName: 'plc',
  num:       'num',
};
export const ANNOT_TYPE_ICONS = {
  normalizing:     'fa-spell-check',
  insertion:       'fa-square-plus',
  // Strikethrough, not a minus: a deletion removes source text, which is what
  // the editorial mark means — and it stays distinct from ATR noise's trash,
  // which discards text as unreadable rather than deleting it deliberately.
  deletion:        'fa-strikethrough',
  atr_noise:       'fa-trash',
  non_resolv_abbr: 'fa-circle-question',
  markup:          'fa-code',
};
export const ANNOT_TYPE_TITLES = {
  normalizing:    'Normalization',
  insertion:      'Insertion',
  deletion:       'Deletion',
  atr_noise:      'ATR Noise',
  non_resolv_abbr: 'Unresolvable Abbreviation',
  markup:         'Markup',
};
export function isSpaceExact(annot) {
  return !isInsertion(annot) && !isAtrNoise(annot) && !isNonResolvAbbr(annot) && getExact(annot).trim() === '';
}

// ── What an annotation can carry ──────────────────────────────────────────────
// An empty value is a deletion. Checked on the value rather than the purpose so
// rows written before derivePurpose existed are classified correctly too.
export function isDeletion(annot) {
  return !isInsertion(annot) && !getBodyValue(annot);
}
// Tag, Gap and Certainty describe the *output* text of an annotation, so they
// only apply where there is output to describe: a deletion emits no tokens at
// all, an insertion has no source, and ATR noise is passed through verbatim
// inside <unclear>. Those three carry no qualifier chips.
export function hasQualifiers(annot) {
  return !isInsertion(annot) && !isAtrNoise(annot) && !isDeletion(annot);
}
// A "resolution" is a substitution that produced a form someone chose — the only
// thing certainty can grade. Narrower than hasQualifiers: an unresolvable
// abbreviation resolves nothing, and markup changes no text.
export function isResolution(annot) {
  return hasQualifiers(annot) && !isNonResolvAbbr(annot) && !isMarkup(annot);
}
// Most annotations are plain normalisations or ATR fixes, where certainty is not
// a question — so that is the default, stored as the absence of a value.
export const CERT_DEFAULT = 'ocr_fix';
export function getCert(annot) { return annot?.body?.[0]?.cert || CERT_DEFAULT; }

// The states split by what they can describe: only an abbreviation *resolution*
// can be more or less certain — a mechanical normalisation resolves nothing.
// Menus render these groups so the distinction is visible at the point of choice.
export const CERT_GROUPS = [
  { label: 'Normalisation & ATR correction', states: ['ocr_fix'] },
  // Ordered by descending certainty, which is also the TEI ramp: high, medium, low.
  { label: 'Abbreviation resolution',        states: ['informed', 'ambiguous', 'arbitrary'] },
];
export const CERT_STATES = CERT_GROUPS.flatMap(g => g.states);

export const CERT_LABELS = {
  informed:  'Informed spelling',
  ambiguous: 'Ambiguous spelling',
  arbitrary: 'Arbitrary spelling',
  ocr_fix:   'Normalisation / OCR Fix',
};

// ── Purpose derived from the value ────────────────────────────────────────────
// Three purposes are not really a choice — they are what the annotation *is*:
// a zero-width target is an insertion, an empty value is a deletion, anything
// else is a normalization. The other three (atr_noise, non_resolv_abbr, markup)
// are deliberate and set the value themselves, so they are never overridden.
// Called at every point a value is written, so the Type chip can never disagree
// with the "deleted" label the row already derives from the value.
const VALUE_DRIVEN_PURPOSES = ['normalizing', 'deletion', 'insertion'];
export function derivePurpose(annot, value) {
  const current = annot?.body?.[0]?.purpose;
  if (current && !VALUE_DRIVEN_PURPOSES.includes(current)) return current;
  if (getStart(annot) === getEnd(annot)) return 'insertion';
  return value ? 'normalizing' : 'deletion';
}

// ── Guideline help ────────────────────────────────────────────────────────────
// One short blurb per category, condensed from the matching section of
// template/guidelines.html, plus the anchor to jump to the full text. Shown as a
// hover popover wherever a category is named (chips and menus).
// `anchor` must match an id in guidelines.html — tests/test_editor_render.py
// checks every one of them still resolves.
export const TYPE_HELP = {
  normalizing: { anchor: 'what-to-normalize', text:
    'Rewrite the whole token to its normalized form: ramist u/v and i/j, HTR letter errors, ' +
    'abbreviation expansions, capitalization, apostrophes and accents. Never edit single letters.' },
  insertion: { anchor: 'g2', text:
    'A missing word space, or a line-break hyphen merged into the next line. ' +
    'Only spaces are ever inserted — never letters.' },
  deletion: { anchor: 'g7', text:
    'Removing a space before punctuation — the one case where deletion is a deliberate choice. ' +
    'Anywhere else it is usually an alignment artifact.' },
  atr_noise: { anchor: 'g10', text:
    'Text too degraded to read confidently. Marking it as noise avoids hallucinating ' +
    'content that is not on the page.' },
  non_resolv_abbr: { anchor: 'g12', text:
    'An abbreviation you cannot justify expanding from context. Keep the initial as ' +
    'written and record which kind of name it stands for.' },
  markup: { anchor: 'entity-tagging', text:
    'Tag the token without changing its text — persons, organisations, places and numerals.' },
};
export const CERT_HELP = {
  informed:  { anchor: 'g13', text:
    'Resolving an abbreviation: context, the rest of the manuscript, or standard usage ' +
    'justifies the expansion you wrote.' },
  arbitrary: { anchor: 'g13', text:
    'You are sure what the word is, but the spelling you picked is one of several ' +
    'defensible ones and nothing in the source settles it.' },
  ambiguous: { anchor: 'g13', text:
    'The source genuinely supports more than one reading and you committed to one. ' +
    'Unlike an Unresolvable Abbreviation, you did resolve it.' },
  ocr_fix:   { anchor: 'g13', text:
    'The default. No abbreviation was resolved — the change is a spelling normalisation ' +
    '(v→u) or an ATR correction, so certainty does not apply.' },
};
export const SEMTAG_HELP = {
  persName:  { anchor: 'entity-tagging', text: 'A person. Tagged independently of any text change.' },
  orgName:   { anchor: 'entity-tagging', text: 'An organisation. Tagged independently of any text change.' },
  placeName: { anchor: 'entity-tagging', text: 'A place. Tagged independently of any text change.' },
  num:       { anchor: 'g9', text:
    'A numeral. Leave it exactly as written — no conversion between Roman, Arabic or ' +
    'fractional systems, and no correction of cardinal/ordinal form.' },
};
// Shown on an untagged Tag chip, where there is no semtag to describe yet.
export const TAG_HELP = { anchor: 'entity-tagging', text:
  'Tag the token as a person, organisation, place or numeral — independently of any ' +
  'text change. A semtag can sit on a Normalization as well as on a Markup.' };
export const GAP_HELP = { anchor: 'g2', text:
  'The token is split across a page or column break. Toggle a gap on that side instead ' +
  'of merging text across pages.' };

const HELP_MAPS = { type: TYPE_HELP, cert: CERT_HELP, semtag: SEMTAG_HELP };
// Human label for each anchor, shown as the popover's footer reference.
const ANCHOR_LABELS = {
  'what-to-normalize': 'What to normalize',
  'entity-tagging':    'Entity tagging',
};
/** Display label for a guidelines anchor: 'g13' → '§ 13', section ids → their title. */
export function anchorLabel(anchor) {
  const m = /^g(\d+)$/.exec(anchor);
  return m ? `§ ${m[1]}` : (ANCHOR_LABELS[anchor] ?? anchor);
}
/** Look up the guideline blurb for a category, e.g. helpFor('cert', 'arbitrary'). */
export function helpFor(kind, key) {
  if (kind === 'gap') return GAP_HELP;
  if (kind === 'semtag' && !key) return TAG_HELP;
  return HELP_MAPS[kind]?.[key] ?? null;
}

// The types a menu may offer, in menu order. 'insertion' is absent on purpose:
// it requires a null source (start === end), so it cannot be chosen — only
// created by insert mode and derived by derivePurpose. Offering it would leave
// purpose:'insertion' on an annotation that still spans text.
export const ANNOT_TYPE_MENU = ['normalizing', 'deletion', 'atr_noise', 'non_resolv_abbr', 'markup'];
// Reasons for an unresolvable abbreviation. Same four entities as SEMTAG_LABELS
// minus 'num', plus a catch-all.
export const NON_RESOLV_REASONS = ['persName', 'orgName', 'placeName', 'other'];
export const NON_RESOLV_REASON_LABELS = { ...SEMTAG_LABELS, other: 'Other' };

// Font Awesome class, or null when the state is drawn with the inline SVG
// (the two-checkboxes-one-ticked glyph) in editor.html.
export const CERT_ICONS = {
  informed:  'fa-lightbulb',
  arbitrary: 'fa-puzzle-piece',
  ambiguous: null,
  ocr_fix:   'fa-wrench',
};

// ── HTML escaping ─────────────────────────────────────────────────────────────
export function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Escape text and render whitespace visibly: · for a literal space, ↵ for a
// newline *within* a token/annotation (e.g. a word split across two ALTO
// lines) — that internal break must stay a compact glyph, not become an
// actual line wrap, so it reads as "this word continues" rather than as the
// page's normal line break.
export function renderVisible(text) {
  return escapeHtml(text ?? '')
    .replace(/ /g, '<span class="tok-ws">·</span>')
    .replace(/\n/g, '<span class="tok-ws">&#8629;</span>');
}

// Like renderVisible, but for the Source panel: that panel already shows
// plain spaces and relies on white-space:pre-wrap for real line breaks, so
// text inside an annotation <mark> should render the same way as the
// surrounding text — just escaped, no ·/↵ glyphs.
export function renderVisibleSource(text) {
  return escapeHtml(text ?? '');
}

// ── Text transformation ───────────────────────────────────────────────────────
export function applyAnnotations(text, annotations) {
  if (!annotations?.length) return text;
  // Single left-to-right pass: emit each untouched gap then each annotation's
  // replacement value, building the result in one array join — O(n + length)
  // instead of the previous O(n × length) repeated full-string slicing (which
  // rebuilt the whole ~400k-char string per annotation on every edit).
  //
  // Sort ascending by start; for equal start, ascending by end so a zero-width
  // insertion (end === start) is emitted *before* a substitution that starts at
  // the same offset — i.e. inserted text precedes the annotated span. This is
  // the same ordering computeNormalizedPositions() uses (insertions first), so
  // the produced text and the position map stay aligned.
  const sorted = [...annotations].sort((a, b) => {
    const ds = getStart(a) - getStart(b);
    return ds !== 0 ? ds : getEnd(a) - getEnd(b);
  });
  const out = [];
  let cursor = 0;
  for (const a of sorted) {
    const s = getStart(a), e = getEnd(a);
    if (s > cursor) out.push(text.slice(cursor, s));  // untouched text before it
    out.push(getBodyValue(a));                         // its replacement/insert value
    cursor = Math.max(cursor, e);
  }
  if (cursor < text.length) out.push(text.slice(cursor));
  return out.join('');
}

// Renders a block divider at each part boundary (after the first), so a
// Document made of several imported parts visibly shows where one ends and
// the next begins instead of reading as one undifferentiated text.
//
// The label is rendered via a CSS ::before on an otherwise-empty element
// (see part-divider/::before in editor.html) — generated content is not
// part of the DOM text, so it's invisible to Range.toString()/textContent
// and doesn't shift the character offsets the editor uses for click/selection
// positions, which assume the rendered text exactly matches fullText.
function _partDividerHtml(part) {
  const label = part.original_filename || `part ${part.part_id}`;
  return `<div class="part-divider" data-part-id="${escapeHtml(String(part.part_id ?? ''))}" `
       + `data-part-label="${escapeHtml(label)}"></div>`;
}

// Escapes text[start:end), splicing in part-divider markup at any boundary
// offsets that fall within the range.
function _escapeWithDividers(text, start, end, boundaries) {
  let html = '';
  let pos = start;
  for (const b of boundaries) {
    if (b.start <= pos || b.start >= end) continue;
    html += escapeHtml(text.slice(pos, b.start)) + _partDividerHtml(b.part);
    pos = b.start;
  }
  html += escapeHtml(text.slice(pos, end));
  return html;
}

// Like _escapeWithDividers, but for a single annotation's <mark>: if a
// part boundary falls inside [start, end), the annotation is split into
// multiple <mark> fragments (same data-annotation id and classes) with the
// divider between them, so the boundary stays visible even when an
// annotation's span crosses it.
function _markWithDividers(text, start, end, boundaries, cls, annotId, renderText) {
  let html = '';
  let pos = start;
  for (const b of boundaries) {
    if (b.start <= pos || b.start >= end) continue;
    if (b.start > pos) {
      html += `<mark class="${cls}" data-annotation="${escapeHtml(annotId)}">${renderText(text.slice(pos, b.start))}</mark>`;
    }
    html += _partDividerHtml(b.part);
    pos = b.start;
  }
  if (pos < end) {
    html += `<mark class="${cls}" data-annotation="${escapeHtml(annotId)}">${renderText(text.slice(pos, end))}</mark>`;
  }
  return html;
}

// ── Source panel HTML ─────────────────────────────────────────────────────────
// Selection highlighting is applied separately by toggling the `.selected`
// class directly on the matching <mark> nodes (see editor.js), so this builder
// is independent of the current selection and only rebuilds when annotations
// actually change.
export function buildSourceHtml(fullText, annotsSorted, partOffsets = []) {
  const text  = fullText;
  const boundaries = partOffsets
    .filter(s => s.start > 0)
    .map(s => ({ start: s.start, part: s }))
    .sort((a, b) => a.start - b.start);
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

    if (s > cursor) html += _escapeWithDividers(text, cursor, s, boundaries);

    const cls = ['r6o-annotation',
      a.validated_by     ? 'r6o-validated'      : '',
      isInsertion(a)     ? 'r6o-insertion'      : '',
      isAtrNoise(a)      ? 'r6o-atr-noise'      : '',
      isNonResolvAbbr(a) ? 'r6o-nonresolv-abbr' : '',
      isMarkup(a)        ? 'r6o-markup'         : '',
    ].filter(Boolean).join(' ');

    if (s === e) {
      html += `<mark class="${cls}" data-annotation="${escapeHtml(a.id)}"></mark>`;
    } else if (renderFrom < e) {
      html += _markWithDividers(text, renderFrom, e, boundaries, cls, a.id, renderVisibleSource);
    }
    cursor = Math.max(cursor, e);
  }

  if (cursor < text.length) html += _escapeWithDividers(text, cursor, text.length, boundaries);
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
// As with buildSourceHtml, the `.norm-highlight` selection class is toggled
// directly on the matching <mark> nodes (see editor.js), so this builder is
// independent of the current selection.
export function buildNormalizedPageHtml(normalizedText, annotsSorted, normalizedPositions) {
  const text      = normalizedText;
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
      a.validated_by     ? 'norm-validated'     : '',
      isAtrNoise(a)      ? 'norm-atr-noise'     : '',
      isNonResolvAbbr(a) ? 'norm-nonresolv-abbr': '',
      isMarkup(a)        ? 'norm-markup'        : '',
    ].filter(Boolean).join(' ');
    html += `<mark class="${cls}" data-annotation="${escapeHtml(a.id)}">${renderVisible(text.slice(pos.start, pos.end))}</mark>`;
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
