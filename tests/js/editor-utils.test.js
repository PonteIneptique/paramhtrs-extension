import { describe, test, expect } from '@jest/globals';
import {
  getSelector, getStart, getEnd, getExact, getPrefix, getSuffix, getBodyValue,
  isInsertion, isAtrNoise, isNonResolvAbbr, getNonResolvReason, isSpaceExact,
  escapeHtml, applyAnnotations,
  buildSourceHtml, computeNormalizedPositions, buildNormalizedPageHtml,
  findSimilarAnnotations,
  findSimilarByExact,
  resolveAnnotationBounds,
  findUnannotatedOccurrences,
} from '../../static/js/editor-utils.js';

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeAnnot({ id = 'a1', start = 0, end = 3, exact = 'foo', prefix = '', suffix = '',
                     value = 'bar', purpose = 'normalizing', validated_by = undefined } = {}) {
  const a = {
    id,
    type: 'Annotation',
    body: [{ type: 'TextualBody', value, purpose }],
    target: {
      selector: [
        { type: 'TextPositionSelector', start, end },
        { type: 'TextQuoteSelector', exact, prefix, suffix },
      ],
    },
  };
  if (validated_by !== undefined) a.validated_by = validated_by;
  return a;
}

function makeNonResolvAnnot({ id = 'nr1', start = 0, end = 3, exact = 'foo', reason = 'other' } = {}) {
  const a = makeAnnot({ id, start, end, exact, value: exact, purpose: 'non_resolv_abbr' });
  a.body[0].reason = reason;
  return a;
}

function makeInsertion({ id = 'ins1', pos = 3, value = 'X', prefix = '', suffix = '' } = {}) {
  return {
    id,
    type: 'Annotation',
    body: [{ type: 'TextualBody', value, purpose: 'insertion' }],
    target: {
      selector: [
        { type: 'TextPositionSelector', start: pos, end: pos },
        { type: 'TextQuoteSelector', exact: '', prefix, suffix },
      ],
    },
  };
}

// ── getSelector ───────────────────────────────────────────────────────────────

describe('getSelector', () => {
  test('returns matching selector', () => {
    const a = makeAnnot();
    expect(getSelector(a, 'TextPositionSelector').start).toBe(0);
    expect(getSelector(a, 'TextQuoteSelector').exact).toBe('foo');
  });

  test('returns empty object for unknown type', () => {
    const a = makeAnnot();
    expect(getSelector(a, 'Unknown')).toEqual({});
  });

  test('handles null / undefined annotation gracefully', () => {
    expect(getSelector(null, 'TextPositionSelector')).toEqual({});
    expect(getSelector(undefined, 'TextPositionSelector')).toEqual({});
  });
});

// ── getStart / getEnd / getExact / getPrefix / getSuffix / getBodyValue ───────

describe('position and quote accessors', () => {
  test('getStart / getEnd return correct values', () => {
    const a = makeAnnot({ start: 5, end: 12 });
    expect(getStart(a)).toBe(5);
    expect(getEnd(a)).toBe(12);
  });

  test('getStart / getEnd default to 0 on missing selector', () => {
    expect(getStart({})).toBe(0);
    expect(getEnd({})).toBe(0);
  });

  test('getExact / getPrefix / getSuffix return stored strings', () => {
    const a = makeAnnot({ exact: 'abb', prefix: 'pre', suffix: 'suf' });
    expect(getExact(a)).toBe('abb');
    expect(getPrefix(a)).toBe('pre');
    expect(getSuffix(a)).toBe('suf');
  });

  test('getBodyValue returns body value', () => {
    const a = makeAnnot({ value: 'abbreviation' });
    expect(getBodyValue(a)).toBe('abbreviation');
  });

  test('getBodyValue returns empty string when body absent', () => {
    expect(getBodyValue({})).toBe('');
    expect(getBodyValue(null)).toBe('');
  });
});

// ── isInsertion ───────────────────────────────────────────────────────────────

describe('isInsertion', () => {
  test('true when purpose is insertion', () => {
    const a = makeAnnot({ start: 5, end: 5, purpose: 'insertion' });
    expect(isInsertion(a)).toBe(true);
  });

  test('true when start === end (zero-width span)', () => {
    const a = makeAnnot({ start: 3, end: 3, purpose: 'normalizing' });
    expect(isInsertion(a)).toBe(true);
  });

  test('false for ordinary substitution', () => {
    const a = makeAnnot({ start: 0, end: 3, purpose: 'normalizing' });
    expect(isInsertion(a)).toBe(false);
  });
});

// ── isAtrNoise ────────────────────────────────────────────────────────────────

describe('isAtrNoise', () => {
  test('true when purpose is atr_noise', () => {
    const a = makeAnnot({ purpose: 'atr_noise' });
    expect(isAtrNoise(a)).toBe(true);
  });

  test('false for normalizing', () => {
    expect(isAtrNoise(makeAnnot())).toBe(false);
  });
});

// ── isSpaceExact ──────────────────────────────────────────────────────────────

describe('isSpaceExact', () => {
  test('true when exact is whitespace-only', () => {
    const a = makeAnnot({ exact: ' ', start: 0, end: 1 });
    expect(isSpaceExact(a)).toBe(true);
  });

  test('false for insertion (even if exact is empty)', () => {
    const a = makeInsertion();
    expect(isSpaceExact(a)).toBe(false);
  });

  test('false when exact has non-space chars', () => {
    expect(isSpaceExact(makeAnnot({ exact: 'ab' }))).toBe(false);
  });
});

// ── escapeHtml ────────────────────────────────────────────────────────────────

describe('escapeHtml', () => {
  test('escapes & < >', () => {
    expect(escapeHtml('a & b < c > d')).toBe('a &amp; b &lt; c &gt; d');
  });

  test('leaves unescaped chars unchanged', () => {
    expect(escapeHtml('hello world')).toBe('hello world');
  });

  test('handles empty string', () => {
    expect(escapeHtml('')).toBe('');
  });
});

// ── applyAnnotations ──────────────────────────────────────────────────────────

describe('applyAnnotations', () => {
  test('single substitution', () => {
    const a = makeAnnot({ start: 0, end: 3, exact: 'foo', value: 'bar' });
    expect(applyAnnotations('fooXYZ', [a])).toBe('barXYZ');
  });

  test('deletion (empty value)', () => {
    const a = makeAnnot({ start: 3, end: 6, exact: 'baz', value: '' });
    expect(applyAnnotations('foobaz', [a])).toBe('foo');
  });

  test('insertion at position', () => {
    const ins = makeInsertion({ pos: 3, value: '|' });
    expect(applyAnnotations('foobar', [ins])).toBe('foo|bar');
  });

  test('multiple substitutions applied right-to-left', () => {
    const a1 = makeAnnot({ id: 'a1', start: 0, end: 2, exact: 'ab', value: 'X' });
    const a2 = makeAnnot({ id: 'a2', start: 3, end: 5, exact: 'de', value: 'Y' });
    expect(applyAnnotations('ab_de', [a1, a2])).toBe('X_Y');
  });

  test('returns original text when annotations is empty', () => {
    expect(applyAnnotations('hello', [])).toBe('hello');
  });

  test('returns original text when annotations is null/undefined', () => {
    expect(applyAnnotations('hello', null)).toBe('hello');
    expect(applyAnnotations('hello', undefined)).toBe('hello');
  });
});

// ── buildSourceHtml ───────────────────────────────────────────────────────────

describe('buildSourceHtml', () => {
  test('wraps annotated span in mark', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, exact: 'foo' });
    const html = buildSourceHtml('foobar', [a], null);
    expect(html).toContain('<mark');
    expect(html).toContain('data-annotation="a1"');
    expect(html).toContain('foo');
    expect(html).toContain('bar');
  });

  test('adds selected class when annotation is selected', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3 });
    const html = buildSourceHtml('foobar', [a], 'a1');
    expect(html).toContain('selected');
  });

  test('does not add selected class for other annotation', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3 });
    const html = buildSourceHtml('foobar', [a], 'other');
    expect(html).not.toContain('selected');
  });

  test('adds r6o-validated class for validated annotation', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, validated_by: 42 });
    const html = buildSourceHtml('foobar', [a], null);
    expect(html).toContain('r6o-validated');
  });

  test('adds r6o-insertion class for zero-width insertion', () => {
    const ins = makeInsertion({ id: 'ins1', pos: 3 });
    const html = buildSourceHtml('foobar', [ins], null);
    expect(html).toContain('r6o-insertion');
    // Zero-width mark has no text content
    expect(html).toMatch(/data-annotation="ins1"><\/mark>/);
  });

  test('escapes HTML entities in source text', () => {
    const html = buildSourceHtml('a & b', [], null);
    expect(html).toContain('&amp;');
    expect(html).not.toContain(' & ');
  });

  test('plain text with no annotations is escaped and returned', () => {
    const html = buildSourceHtml('hello', [], null);
    expect(html).toBe('hello');
  });
});

// ── computeNormalizedPositions ────────────────────────────────────────────────

describe('computeNormalizedPositions', () => {
  test('single substitution with longer replacement', () => {
    // 'foo' (len 3) → 'longword' (len 8): delta = +5
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, value: 'longword' });
    const pos = computeNormalizedPositions([a]);
    expect(pos['a1']).toEqual({ start: 0, end: 8 });
  });

  test('single substitution with shorter replacement', () => {
    // 'foo' (len 3) → 'X' (len 1): delta = -2
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, value: 'X' });
    const pos = computeNormalizedPositions([a]);
    expect(pos['a1']).toEqual({ start: 0, end: 1 });
  });

  test('deletion leaves zero-length span', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, value: '' });
    const pos = computeNormalizedPositions([a]);
    expect(pos['a1']).toEqual({ start: 0, end: 0 });
  });

  test('two sequential substitutions accumulate delta', () => {
    // 'ab' (len 2) at [0,2] → 'XY' (len 2): no delta
    // 'cd' (len 2) at [3,5] → 'Z'  (len 1): delta -1 after
    const a1 = makeAnnot({ id: 'a1', start: 0, end: 2, value: 'XY' });
    const a2 = makeAnnot({ id: 'a2', start: 3, end: 5, value: 'Z' });
    const pos = computeNormalizedPositions([a1, a2]);
    expect(pos['a1']).toEqual({ start: 0, end: 2 });
    expect(pos['a2']).toEqual({ start: 3, end: 4 });
  });

  test('insertion at same position as substitution is ordered first', () => {
    // insertion at pos 3 adds 'I'; substitution at [3,6] maps to [4,7] in normalized
    const ins  = makeInsertion({ id: 'ins1', pos: 3, value: 'I' });
    const subst = makeAnnot({ id: 'a1', start: 3, end: 6, value: 'XYZ' });
    const pos = computeNormalizedPositions([subst, ins]); // order shouldn't matter
    expect(pos['ins1']).toEqual({ start: 3, end: 4 });
    expect(pos['a1']).toEqual({ start: 4, end: 7 });
  });
});

// ── buildNormalizedPageHtml ───────────────────────────────────────────────────

describe('buildNormalizedPageHtml', () => {
  test('annotated span is wrapped in mark with norm-annot class', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, value: 'bar' });
    const normalizedText = 'barXYZ';
    const positions = { a1: { start: 0, end: 3 } };
    const html = buildNormalizedPageHtml(normalizedText, [a], null, positions);
    expect(html).toContain('norm-annot');
    expect(html).toContain('data-annotation="a1"');
    expect(html).toContain('bar');
  });

  test('adds norm-highlight class for selected annotation', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, value: 'bar' });
    const positions = { a1: { start: 0, end: 3 } };
    const html = buildNormalizedPageHtml('barXYZ', [a], 'a1', positions);
    expect(html).toContain('norm-highlight');
  });

  test('skips annotations with zero-length span in normalized text', () => {
    const a = makeAnnot({ id: 'a1', start: 0, end: 3, value: '' });
    const positions = { a1: { start: 0, end: 0 } };
    const html = buildNormalizedPageHtml('XYZ', [a], null, positions);
    expect(html).not.toContain('data-annotation="a1"');
  });
});

// ── findSimilarAnnotations ────────────────────────────────────────────────────

describe('findSimilarAnnotations', () => {
  test('finds unvalidated annotations with same exact and value', () => {
    const target = makeAnnot({ id: 't', start: 0, end: 3, exact: 'foo', value: 'bar' });
    const similar = makeAnnot({ id: 's', start: 10, end: 13, exact: 'foo', value: 'bar' });
    const unrelated = makeAnnot({ id: 'u', start: 20, end: 23, exact: 'baz', value: 'qux' });
    const result = findSimilarAnnotations([target, similar, unrelated], target);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('s');
  });

  test('excludes the target annotation itself', () => {
    const target = makeAnnot({ id: 't', exact: 'foo', value: 'bar' });
    const result = findSimilarAnnotations([target], target);
    expect(result).toHaveLength(0);
  });

  test('excludes already-validated annotations', () => {
    const target  = makeAnnot({ id: 't',  exact: 'foo', value: 'bar' });
    const already = makeAnnot({ id: 'v',  exact: 'foo', value: 'bar', validated_by: 1 });
    const result = findSimilarAnnotations([target, already], target);
    expect(result).toHaveLength(0);
  });

  test('returns empty array when no similar annotations exist', () => {
    const target = makeAnnot({ id: 't', exact: 'foo', value: 'bar' });
    const other  = makeAnnot({ id: 'o', exact: 'abc', value: 'xyz' });
    expect(findSimilarAnnotations([target, other], target)).toHaveLength(0);
  });
});

// ── findSimilarByExact ────────────────────────────────────────────────────────

describe('findSimilarByExact', () => {
  test('finds unvalidated annotations with same exact text, regardless of value', () => {
    const target  = makeAnnot({ id: 't', exact: 'foo', value: 'bar' });
    const sameVal = makeAnnot({ id: 's1', exact: 'foo', value: 'bar' });
    const diffVal = makeAnnot({ id: 's2', exact: 'foo', value: 'baz' });
    const result = findSimilarByExact([target, sameVal, diffVal], target);
    expect(result).toHaveLength(2);
    expect(result.map(a => a.id)).toEqual(expect.arrayContaining(['s1', 's2']));
  });

  test('excludes the target annotation itself', () => {
    const target = makeAnnot({ id: 't', exact: 'foo' });
    expect(findSimilarByExact([target], target)).toHaveLength(0);
  });

  test('excludes already-validated annotations', () => {
    const target    = makeAnnot({ id: 't',  exact: 'foo' });
    const validated = makeAnnot({ id: 'v',  exact: 'foo', validated_by: 1 });
    expect(findSimilarByExact([target, validated], target)).toHaveLength(0);
  });

  test('excludes insertion annotations from regular annotation matches', () => {
    const target    = makeAnnot({ id: 't', exact: 'foo' });
    const insertion = makeInsertion({ id: 'i' });
    expect(findSimilarByExact([target, insertion], target)).toHaveLength(0);
  });

  test('excludes ATR noise annotations', () => {
    const target  = makeAnnot({ id: 't', exact: 'foo' });
    const atrNoise = makeAnnot({ id: 'n', exact: 'foo', purpose: 'atr_noise' });
    expect(findSimilarByExact([target, atrNoise], target)).toHaveLength(0);
  });

  test('returns empty array when no matching exact text', () => {
    const target = makeAnnot({ id: 't', exact: 'foo' });
    const other  = makeAnnot({ id: 'o', exact: 'bar' });
    expect(findSimilarByExact([target, other], target)).toHaveLength(0);
  });

  test('for insertion target: finds other insertions with same body value', () => {
    const target = makeInsertion({ id: 't', pos: 5, value: ';' });
    const same   = makeInsertion({ id: 's', pos: 20, value: ';' });
    const diff   = makeInsertion({ id: 'd', pos: 30, value: '.' });
    const result = findSimilarByExact([target, same, diff], target);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('s');
  });

  test('for insertion target: excludes validated insertions', () => {
    const target    = makeInsertion({ id: 't', value: ';' });
    const validated = { ...makeInsertion({ id: 'v', value: ';' }), validated_by: 1 };
    expect(findSimilarByExact([target, validated], target)).toHaveLength(0);
  });

  test('for insertion target: does not match regular annotations', () => {
    const target  = makeInsertion({ id: 't', value: 'foo' });
    const regular = makeAnnot({ id: 'r', exact: 'foo' });
    expect(findSimilarByExact([target, regular], target)).toHaveLength(0);
  });

  test('for insertion target: returns empty when value is whitespace', () => {
    const target = makeInsertion({ id: 't', value: ' ' });
    const other  = makeInsertion({ id: 'o', value: ' ' });
    expect(findSimilarByExact([target, other], target)).toHaveLength(0);
  });

  test('for space-exact target: returns empty', () => {
    const target = makeAnnot({ id: 't', exact: ' ', value: '' });
    const other  = makeAnnot({ id: 'o', exact: ' ', value: '' });
    expect(findSimilarByExact([target, other], target)).toHaveLength(0);
  });

  test('excludes non-resolv-abbr annotations', () => {
    const target   = makeAnnot({ id: 't', exact: 'foo' });
    const nonResolv = makeNonResolvAnnot({ id: 'nr', exact: 'foo' });
    expect(findSimilarByExact([target, nonResolv], target)).toHaveLength(0);
  });
});

// ── isNonResolvAbbr ───────────────────────────────────────────────────────────

describe('isNonResolvAbbr', () => {
  test('true when purpose is non_resolv_abbr', () => {
    expect(isNonResolvAbbr(makeNonResolvAnnot())).toBe(true);
  });

  test('false for normalizing', () => {
    expect(isNonResolvAbbr(makeAnnot())).toBe(false);
  });

  test('false for atr_noise', () => {
    expect(isNonResolvAbbr(makeAnnot({ purpose: 'atr_noise' }))).toBe(false);
  });

  test('false for null', () => {
    expect(isNonResolvAbbr(null)).toBe(false);
  });
});

// ── getNonResolvReason ────────────────────────────────────────────────────────

describe('getNonResolvReason', () => {
  test('returns stored reason', () => {
    expect(getNonResolvReason(makeNonResolvAnnot({ reason: 'persName' }))).toBe('persName');
  });

  test('returns orgName when set', () => {
    expect(getNonResolvReason(makeNonResolvAnnot({ reason: 'orgName' }))).toBe('orgName');
  });

  test('defaults to "other" when reason field is absent', () => {
    const a = makeAnnot({ purpose: 'non_resolv_abbr' });
    expect(getNonResolvReason(a)).toBe('other');
  });

  test('defaults to "other" for null annotation', () => {
    expect(getNonResolvReason(null)).toBe('other');
  });
});

// ── isSpaceExact: non_resolv_abbr not confused for space ──────────────────────

describe('isSpaceExact with non_resolv_abbr', () => {
  test('false for non_resolv_abbr with space-only exact', () => {
    const a = makeNonResolvAnnot({ exact: ' ' });
    expect(isSpaceExact(a)).toBe(false);
  });
});

// ── resolveAnnotationBounds ───────────────────────────────────────────────────

describe('resolveAnnotationBounds', () => {
  test('no existing annotations: returns original bounds', () => {
    expect(resolveAnnotationBounds(0, 8, [])).toEqual({ start: 0, end: 8 });
  });

  test('non-overlapping annotation: returns original bounds', () => {
    const existing = [makeAnnot({ id: 'a1', start: 10, end: 15 })];
    expect(resolveAnnotationBounds(0, 8, existing)).toEqual({ start: 0, end: 8 });
  });

  test('overlap at end: trims end to existing start', () => {
    const existing = [makeAnnot({ id: 'a1', start: 5, end: 10 })];
    expect(resolveAnnotationBounds(0, 8, existing)).toEqual({ start: 0, end: 5 });
  });

  test('overlap at start: advances start to existing end', () => {
    const existing = [makeAnnot({ id: 'a1', start: 0, end: 5 })];
    expect(resolveAnnotationBounds(2, 8, existing)).toEqual({ start: 5, end: 8 });
  });

  test('fully covered by one annotation: returns null', () => {
    const existing = [makeAnnot({ id: 'a1', start: 0, end: 10 })];
    expect(resolveAnnotationBounds(2, 8, existing)).toBeNull();
  });

  test('selection starts exactly at existing start: returns null', () => {
    const existing = [makeAnnot({ id: 'a1', start: 0, end: 5 })];
    expect(resolveAnnotationBounds(0, 8, existing)).toBeNull();
  });

  test('selection ends exactly at existing end (no overlap): returns original', () => {
    const existing = [makeAnnot({ id: 'a1', start: 5, end: 10 })];
    expect(resolveAnnotationBounds(0, 5, existing)).toEqual({ start: 0, end: 5 });
  });

  test('zero-width insertion is ignored for overlap', () => {
    const existing = [makeInsertion({ id: 'ins1', pos: 5 })];
    expect(resolveAnnotationBounds(0, 8, existing)).toEqual({ start: 0, end: 8 });
  });

  test('multiple overlaps: stops at first encountered', () => {
    const existing = [
      makeAnnot({ id: 'a1', start: 3, end: 5 }),
      makeAnnot({ id: 'a2', start: 6, end: 8 }),
    ];
    expect(resolveAnnotationBounds(0, 10, existing)).toEqual({ start: 0, end: 3 });
  });

  test('adjacent annotation before selection: returns original bounds', () => {
    const existing = [makeAnnot({ id: 'a1', start: 0, end: 3 })];
    expect(resolveAnnotationBounds(3, 8, existing)).toEqual({ start: 3, end: 8 });
  });

  test('adjacent annotation after selection: returns original bounds', () => {
    const existing = [makeAnnot({ id: 'a1', start: 8, end: 12 })];
    expect(resolveAnnotationBounds(3, 8, existing)).toEqual({ start: 3, end: 8 });
  });
});

describe('findUnannotatedOccurrences', () => {
  const text = 'Jo. was here and Jo. was there and Jo. again';
  //            0123456789...         17  18 19 20  34  35 36 37

  test('no annotations: returns all occurrences', () => {
    const result = findUnannotatedOccurrences(text, 'Jo.', []);
    expect(result).toEqual([
      { start: 0,  end: 3  },
      { start: 17, end: 20 },
      { start: 35, end: 38 },
    ]);
  });

  test('annotation covering first occurrence: skips it, returns rest', () => {
    const existing = [makeAnnot({ id: 'a1', start: 0, end: 3, exact: 'Jo.' })];
    const result = findUnannotatedOccurrences(text, 'Jo.', existing);
    expect(result).toEqual([
      { start: 17, end: 20 },
      { start: 35, end: 38 },
    ]);
  });

  test('all occurrences covered: returns []', () => {
    const existing = [
      makeAnnot({ id: 'a1', start: 0,  end: 3  }),
      makeAnnot({ id: 'a2', start: 17, end: 20 }),
      makeAnnot({ id: 'a3', start: 35, end: 38 }),
    ];
    expect(findUnannotatedOccurrences(text, 'Jo.', existing)).toEqual([]);
  });

  test('empty exact: returns []', () => {
    expect(findUnannotatedOccurrences(text, '', [])).toEqual([]);
  });

  test('whitespace-only exact: returns []', () => {
    expect(findUnannotatedOccurrences(text, '   ', [])).toEqual([]);
  });

  test('insertion annotation does not block a candidate', () => {
    const ins = makeInsertion({ id: 'ins1', pos: 0 });
    const result = findUnannotatedOccurrences(text, 'Jo.', [ins]);
    expect(result).toHaveLength(3);
  });

  test('non-resolv annotation blocks its span', () => {
    const existing = [makeNonResolvAnnot({ id: 'nr1', start: 0, end: 3, exact: 'Jo.' })];
    const result = findUnannotatedOccurrences(text, 'Jo.', existing);
    expect(result).not.toContainEqual({ start: 0, end: 3 });
    expect(result).toHaveLength(2);
  });

  test('ATR noise annotation blocks its span', () => {
    const existing = [makeAnnot({ id: 'a1', start: 17, end: 20, exact: 'Jo.', purpose: 'atr_noise', value: 'Jo.' })];
    const result = findUnannotatedOccurrences(text, 'Jo.', existing);
    expect(result).not.toContainEqual({ start: 17, end: 20 });
    expect(result).toHaveLength(2);
  });

  test('adjacent annotation (touching but not overlapping) does not block', () => {
    // annotation ends exactly where 'Jo.' starts at pos 17
    const existing = [makeAnnot({ id: 'a1', start: 14, end: 17 })];
    const result = findUnannotatedOccurrences(text, 'Jo.', existing);
    expect(result).toContainEqual({ start: 17, end: 20 });
  });

  test('exact not present in text: returns []', () => {
    expect(findUnannotatedOccurrences(text, 'xyz', [])).toEqual([]);
  });
});
