import { describe, test, expect } from '@jest/globals';
import {
  getSelector, getStart, getEnd, getExact, getPrefix, getSuffix, getBodyValue,
  isInsertion, isAtrNoise, isSpaceExact,
  escapeHtml, applyAnnotations,
  buildSourceHtml, computeNormalizedPositions, buildNormalizedPageHtml,
  findSimilarAnnotations,
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
