import { createApp } from 'vue';
import {
  getSelector, getStart, getEnd, getExact, getPrefix, getSuffix, getBodyValue,
  isInsertion, isAtrNoise, isNonResolvAbbr, getNonResolvReason, isSpaceExact,
  escapeHtml, applyAnnotations,
  buildSourceHtml, computeNormalizedPositions, buildNormalizedPageHtml,
  findSimilarAnnotations,
  findSimilarByExact,
  resolveAnnotationBounds,
  findUnannotatedOccurrences,
} from './editor-utils.js';

// Module-level pending annotation (raw W3C object, not reactive)
let pendingAnnotRaw = null;

function _textParts(str) {
  return str.split('\n').map((t, i, a) => ({ text: t, br: i < a.length - 1 }));
}

export function createEditorApp(config) {
  const CURRENT_USER_ID = config.currentUserId;
  const urls = config.urls;

  return createApp({
    delimiters: ['[[', ']]'],
    data() {
      return {
        lines:               config.lines,
        fullText:            config.fullText,
        annotations:         config.annotations,
        pageId:              config.pageId,
        pageStatus:          config.pageStatus,
        hoveredAnnotationId: null,
        selectedAnnotationId: null,
        pendingAnnot:        null,
        insertMode:          false,
        refineMode:          false,
        annotFilter:         'pending',
        annotSort:           'position',
        pendingUnclearOpen:  false,
        focusUnclearOpen:    false,
        focusMenuPos:        { top: 0, left: 0 },
        fontSize:            1,
        sourceWidth:         33,
        annotsWidth:         28,
        saveError:           false,
        bulkCandidates:      [],
        bulkChecked:         {},
        bulkMode:            'validate',
        showAnnotContext:     false,
        focusMode:           false,
        focusAnnotIndex:     0,
        focusEditValue:      '',
        focusValidated:      false,
      };
    },

    computed: {
      allAnnotationsSorted() {
        return [...this.annotations].sort((a, b) => getStart(a) - getStart(b));
      },
      pendingAnnotationsSorted() {
        const list = this.allAnnotationsSorted.filter(a => !a.validated_by);
        return this.annotSort === 'alpha'
          ? [...list].sort((a, b) => getExact(a).localeCompare(getExact(b), undefined, { sensitivity: 'base' }))
          : list;
      },
      validatedAnnotationsSorted() {
        const list = this.allAnnotationsSorted.filter(a => a.validated_by);
        return this.annotSort === 'alpha'
          ? [...list].sort((a, b) => getExact(a).localeCompare(getExact(b), undefined, { sensitivity: 'base' }))
          : list;
      },
      panelSourceStyle() { return { flex: `0 0 ${this.sourceWidth}%` }; },
      panelAnnotsStyle() { return { flex: `0 0 ${this.annotsWidth}%` }; },

      sourceHtml() {
        return buildSourceHtml(this.fullText, this.allAnnotationsSorted, this.selectedAnnotationId);
      },

      normalizedPageText() { return applyAnnotations(this.fullText, this.annotations); },

      normalizedPositions() { return computeNormalizedPositions(this.annotations); },

      normalizedPageHtml() {
        return buildNormalizedPageHtml(
          this.normalizedPageText,
          this.allAnnotationsSorted,
          this.selectedAnnotationId,
          this.normalizedPositions,
        );
      },

      focusAnnotations() {
        return this.pendingAnnotationsSorted.filter(a => !isInsertion(a));
      },
      focusCurrent() {
        if (!this.focusAnnotations.length) return null;
        return this.focusAnnotations[Math.min(this.focusAnnotIndex, this.focusAnnotations.length - 1)];
      },
      focusWindowSegs() {
        if (!this.focusCurrent) return [];
        const text      = this.fullText;
        const focusAnns = this.focusAnnotations;
        const allAnns   = this.allAnnotationsSorted;
        const cur       = this.focusCurrent;
        const wS        = Math.max(0, getStart(cur) - 500);
        const wE        = Math.min(text.length, getEnd(cur) + 500);
        const inW       = allAnns.filter(a => getStart(a) >= wS && getEnd(a) <= wE);
        const segs = []; let pos = wS;
        for (const a of inW) {
          const s = getStart(a), e = getEnd(a);
          if (s > pos) segs.push({ type:'t', parts: _textParts(text.slice(pos, s)) });
          const focusIdx   = focusAnns.indexOf(a);
          const isNavigable = focusIdx >= 0;
          segs.push({ type:'a', annId:a.id, isCurrent: a.id===cur.id, isNavigable,
                      abbr: getExact(a), norm: getBodyValue(a),
                      annIdx: isNavigable ? focusIdx : -1 });
          pos = e;
        }
        if (pos < wE) segs.push({ type:'t', parts: _textParts(text.slice(pos, wE)) });
        if (segs[0]?.type === 't' && segs[0].parts.length)
          segs[0].parts[0].text = segs[0].parts[0].text.replace(/^\s+/, '');
        return segs;
      },
      focusAnnData() {
        if (!this.focusCurrent) return { left:[], right:[] };
        const text = this.fullText;
        const anns = this.focusAnnotations;
        const cur  = this.focusCurrent;
        const MAXD = 10;
        const wS   = Math.max(0, getStart(cur) - 180);
        const wE   = Math.min(text.length, getEnd(cur) + 180);
        const inW  = anns.filter(a => getStart(a) >= wS && getEnd(a) <= wE);
        const segs = []; let pos = wS;
        for (const a of inW) {
          const s = getStart(a), e = getEnd(a);
          if (s > pos) {
            const d = text.slice(pos, s).replace(/\n+/g,' ↵ ').trim();
            if (d) segs.push({ type:'t', display: d });
          }
          segs.push({ type:'a', annId:a.id, isCurrent:a.id===cur.id,
                      abbr:getExact(a), norm:getBodyValue(a), annIdx:anns.indexOf(a) });
          pos = e;
        }
        if (pos < wE) {
          const d = text.slice(pos, wE).replace(/\n+/g,' ↵ ').trim();
          if (d) segs.push({ type:'t', display: d });
        }
        const ci = segs.findIndex(s => s.type==='a' && s.isCurrent);
        const _fade = (s, d) => {
          const f = Math.max(0.18, Math.pow(Math.max(0, 1 - d/MAXD), 1.3) * (s.type==='a'? 0.78:0.72));
          return { ...s, opacity: f };
        };
        let n=0; const left  = [...segs.slice(0, ci)].reverse().map(s => { if(s.type==='a') n++; return _fade(s,n); }).reverse();
        n=0;     const right = segs.slice(ci+1).map(s => { if(s.type==='a') n++; return _fade(s,n); });
        return { left, right };
      },
    },

    watch: {
      fontSize(val) {
        document.getElementById('editor-root').style.setProperty('--editor-font', val + 'rem');
      },
    },

    mounted() {
      document.getElementById('editor-root').style.setProperty('--editor-font', this.fontSize + 'rem');
      const el = this.$refs.pageSource;
      this._registerSourceListeners(el);
      this._registerNormalizedListeners(this.$refs.normalizedText);
      document.addEventListener('keydown', this._handleKeydown);
      this._closeDropdowns = (e) => {
        if (!e.target.closest('.unclear-wrap') && !e.target.closest('.fm-unclear-wrap')) {
          this.pendingUnclearOpen = false;
          this.focusUnclearOpen   = false;
        }
      };
      document.addEventListener('click', this._closeDropdowns);
    },
    beforeUnmount() {
      document.removeEventListener('keydown', this._handleKeydown);
      document.removeEventListener('click', this._closeDropdowns);
    },

    methods: {
      getExact, getPrefix, getSuffix, getBodyValue,
      isInsertion, isAtrNoise, isNonResolvAbbr, getNonResolvReason, isSpaceExact,
      isInsertionExact(stub) { return stub?.isIns === true; },

      // ── DOM event listeners on #page-source (registered ONCE at mount) ────────
      _registerSourceListeners(el) {
        el.addEventListener('click', (evt) => {
          if (this.insertMode) {
            let pos = 0;
            const pr = document.createRange();
            pr.setStart(el, 0);
            if (document.caretPositionFromPoint) {
              const cp = document.caretPositionFromPoint(evt.clientX, evt.clientY);
              if (cp) { pr.setEnd(cp.offsetNode, cp.offset); pos = pr.toString().length; }
            } else if (document.caretRangeFromPoint) {
              const cr = document.caretRangeFromPoint(evt.clientX, evt.clientY);
              if (cr) { pr.setEnd(cr.startContainer, cr.startOffset); pos = pr.toString().length; }
            }
            const t  = this.fullText;
            const id = crypto.randomUUID();
            pendingAnnotRaw = { id, type:'Annotation', body:[],
              target:{ annotation:id, selector:[
                { type:'TextPositionSelector', start:pos, end:pos },
                { type:'TextQuoteSelector', exact:'',
                  prefix:t.slice(Math.max(0,pos-10),pos), suffix:t.slice(pos,pos+10) },
              ]}};
            this.pendingAnnot = { id, exact:'', isIns:true };
            this.insertMode = false;
            this.$nextTick(() => {
              const inp = this.$refs.pendingInput;
              if (inp) (Array.isArray(inp) ? inp[0] : inp).focus();
            });
            return;
          }

          const span = evt.target.closest('[data-annotation]');
          if (span) {
            const id = span.dataset.annotation;
            const newSel = this.selectedAnnotationId === id ? null : id;
            this.selectedAnnotationId = newSel;
            if (newSel) {
              const annot = this.allAnnotationsSorted.find(a => a.id === id);
              if (annot) this._focusAnnotInput(annot);
            }
          }
        });

        el.addEventListener('mouseup', () => {
          const sel = window.getSelection();
          if (!sel || sel.isCollapsed || !sel.rangeCount) return;
          const range = sel.getRangeAt(0);
          if (!el.contains(range.commonAncestorContainer)) return;

          const pr = document.createRange();
          pr.setStart(el, 0);
          pr.setEnd(range.startContainer, range.startOffset);
          const rawStart = pr.toString().length;
          const rawEnd   = rawStart + range.toString().length;
          if (rawStart === rawEnd) return;

          const t = this.fullText;

          if (this.refineMode && this.selectedAnnotationId) {
            const tid    = this.selectedAnnotationId;
            const others = this.annotations.filter(a => a.id !== tid);
            const bounds = resolveAnnotationBounds(rawStart, rawEnd, others);
            if (!bounds) { sel.removeAllRanges(); return; }
            const { start, end } = bounds;
            const exact  = t.slice(start, end);
            const prefix = t.slice(Math.max(0, start - 10), start);
            const suffix = t.slice(end, end + 10);
            let updated;
            this.annotations = this.annotations.map(a => {
              if (a.id !== tid) return a;
              updated = { ...a, target: { ...a.target, selector: [
                { type:'TextPositionSelector', start, end },
                { type:'TextQuoteSelector', exact, prefix, suffix },
              ]}};
              return updated;
            });
            this.saveAnnotation(updated);
            this.refineMode = false;
            sel.removeAllRanges();
            return;
          }

          const bounds = resolveAnnotationBounds(rawStart, rawEnd, this.annotations);
          if (!bounds) { sel.removeAllRanges(); return; }
          const { start, end } = bounds;
          const exact  = t.slice(start, end);
          const prefix = t.slice(Math.max(0, start - 10), start);
          const suffix = t.slice(end, end + 10);

          const id = crypto.randomUUID();
          pendingAnnotRaw = { id, type:'Annotation', body:[],
            target:{ annotation:id, selector:[
              { type:'TextPositionSelector', start, end },
              { type:'TextQuoteSelector', exact, prefix, suffix },
            ]}};
          this.pendingAnnot = { id, exact };
          this.$nextTick(() => {
            const inp = this.$refs.pendingInput;
            if (inp) (Array.isArray(inp) ? inp[0] : inp).focus();
          });
        });

        el.addEventListener('mouseover', (evt) => {
          if (this.selectedAnnotationId) return;
          const span = evt.target.closest('[data-annotation]');
          if (!span) return;
          const id = span.dataset.annotation;
          if (id !== this.hoveredAnnotationId) {
            el.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
            span.classList.add('hovered');
            this.hoveredAnnotationId = id;
            this._scrollAnnotRowIntoView(id);
          }
        });
        el.addEventListener('mouseout', (evt) => {
          const from = evt.target.closest('[data-annotation]');
          const to   = evt.relatedTarget?.closest?.('[data-annotation]');
          if (from && from !== to) {
            from.classList.remove('hovered');
            this.hoveredAnnotationId = null;
          }
        });
      },

      // ── Normalized panel listeners ────────────────────────────────────────────
      _registerNormalizedListeners(el) {
        el.addEventListener('mouseover', (evt) => {
          if (this.selectedAnnotationId) return;
          const span = evt.target.closest('[data-annotation]');
          if (!span) return;
          const id = span.dataset.annotation;
          if (id === this.hoveredAnnotationId) return;
          el.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
          const src = this.$refs.pageSource;
          src.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
          span.classList.add('hovered');
          src.querySelector(`[data-annotation="${CSS.escape(id)}"]`)?.classList.add('hovered');
          this.hoveredAnnotationId = id;
          this._scrollAnnotRowIntoView(id);
        });
        el.addEventListener('mouseout', (evt) => {
          const from = evt.target.closest('[data-annotation]');
          const to   = evt.relatedTarget?.closest?.('[data-annotation]');
          if (from && from !== to) {
            from.classList.remove('hovered');
            const id = from.dataset.annotation;
            this.$refs.pageSource.querySelector(`[data-annotation="${CSS.escape(id)}"]`)?.classList.remove('hovered');
            this.hoveredAnnotationId = null;
          }
        });
        el.addEventListener('click', (evt) => {
          const span = evt.target.closest('[data-annotation]');
          if (!span) return;
          const id = span.dataset.annotation;
          const newSel = this.selectedAnnotationId === id ? null : id;
          this.selectedAnnotationId = newSel;
          if (newSel) {
            const annot = this.allAnnotationsSorted.find(a => a.id === id);
            if (annot) this._focusAnnotInput(annot);
          }
        });
      },

      // ── Middle-panel helpers ──────────────────────────────────────────────────
      _findAnnotRow(id)   { return document.querySelector(`.panel-annots [data-annot-id="${id}"]`); },
      _annotPanelHeaderHeight() {
        const h = document.querySelector('.panel-annots .panel-header');
        return h ? h.offsetHeight : 0;
      },
      _scrollAnnotRowIntoView(id) {
        setTimeout(() => {
          const row = this._findAnnotRow(id); if (!row) return;
          const p = document.querySelector('.panel-annots'); if (!p) return;
          p.scrollTop = row.offsetTop - p.offsetTop - this._annotPanelHeaderHeight();
        }, 0);
      },
      _focusAnnotInput(annot) {
        setTimeout(() => {
          const row = this._findAnnotRow(annot.id); if (!row) return;
          const p = document.querySelector('.panel-annots'); if (!p) return;
          p.scrollTop = row.offsetTop - p.offsetTop - this._annotPanelHeaderHeight();
          row.querySelector('.annot-target')?.focus();
        }, 0);
      },
      onRowMousedown(annot, event) {
        if (event.target.closest('button') || event.target.closest('.annot-target')) return;
        event.preventDefault();
        this.selectAnnotation(annot);
      },
      onRowMouseenter(id) {
        if (this.selectedAnnotationId) return;
        const src  = this.$refs.pageSource;
        const norm = this.$refs.normalizedText;
        src.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
        norm.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
        src.querySelector(`[data-annotation="${CSS.escape(id)}"]`)?.classList.add('hovered');
        norm.querySelector(`[data-annotation="${CSS.escape(id)}"]`)?.classList.add('hovered');
        this.hoveredAnnotationId = id;
      },
      onRowMouseleave() {
        this.$refs.pageSource.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
        this.$refs.normalizedText.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
        this.hoveredAnnotationId = null;
      },

      // ── Annotation value edit ─────────────────────────────────────────────────
      onAnnotBlur(annot, evt) {
        if (!annot.body?.[0]) return;
        const domValue = evt.target.value;
        // Skip save when value hasn't changed — happens after Ctrl+Enter already
        // folded the value into validateAnnotation, then focus moves to the next
        // annotation and this input blurs a second time.
        if (domValue === (annot.body[0].value ?? '')) return;
        const updated = { ...annot, resp_id: CURRENT_USER_ID, body: [{ ...annot.body[0], value: domValue }] };
        this.annotations = this.annotations.map(a => a.id !== annot.id ? a : updated);
        this.saveAnnotation(updated);
      },

      // ── Commit pending annotation ─────────────────────────────────────────────
      commitPending(value) {
        if (!pendingAnnotRaw) return;
        const annot = pendingAnnotRaw; pendingAnnotRaw = null; this.pendingAnnot = null;
        this.pendingUnclearOpen = false;
        const posSel = getSelector(annot, 'TextPositionSelector');
        annot.body   = [{ type:'TextualBody', value: value ?? '',
                          purpose: posSel.start === posSel.end ? 'insertion' : 'normalizing' }];
        annot.resp_id = CURRENT_USER_ID;
        this.annotations = [...this.annotations, annot];
        this.saveAnnotation(annot);
        this._offerBulkAnnotation(annot);
      },

      cancelPending() { pendingAnnotRaw = null; this.pendingAnnot = null; this.pendingUnclearOpen = false; },

      onPendingBlur(evt) {
        const row = evt.currentTarget.closest('.annot-pending');
        if (row && row.contains(evt.relatedTarget)) return;
        this.commitPending(evt.target.value);
      },

      // ── Mark selection as ATR noise ───────────────────────────────────────────
      markAtrNoise() {
        if (!pendingAnnotRaw) return;
        const annot = pendingAnnotRaw; pendingAnnotRaw = null; this.pendingAnnot = null;
        const exact = getSelector(annot, 'TextQuoteSelector').exact ?? '';
        annot.body = [{ type: 'TextualBody', value: exact, purpose: 'atr_noise' }];
        annot.resp_id = CURRENT_USER_ID;
        this.annotations = [...this.annotations, annot];
        this.saveAnnotation(annot);
        this._offerBulkAnnotation(annot);
      },

      // ── Mark selection as non-resolvable abbreviation ────────────────────────
      markNonResolvAbbr(reason) {
        if (!pendingAnnotRaw) return;
        const annot = pendingAnnotRaw; pendingAnnotRaw = null; this.pendingAnnot = null;
        this.pendingUnclearOpen = false;
        const exact = getSelector(annot, 'TextQuoteSelector').exact ?? '';
        annot.body = [{ type: 'TextualBody', value: exact, purpose: 'non_resolv_abbr', reason }];
        annot.resp_id = CURRENT_USER_ID;
        this.annotations = [...this.annotations, annot];
        this.saveAnnotation(annot);
        this._offerBulkAnnotation(annot);
      },

      // ── Bulk annotation offer ─────────────────────────────────────────────────
      _offerBulkAnnotation(annot) {
        const exact = getExact(annot);
        if (!exact || !exact.trim() || getStart(annot) === getEnd(annot)) return;
        const t = this.fullText;
        const occurrences = findUnannotatedOccurrences(t, exact, this.annotations);
        if (!occurrences.length) return;
        const drafts = occurrences.map(({ start, end }) => {
          const id = crypto.randomUUID();
          return {
            id, type: 'Annotation', resp_id: CURRENT_USER_ID,
            body: JSON.parse(JSON.stringify(annot.body)),
            target: { annotation: id, selector: [
              { type: 'TextPositionSelector', start, end },
              { type: 'TextQuoteSelector',
                exact: t.slice(start, end),
                prefix: t.slice(Math.max(0, start - 10), start),
                suffix: t.slice(end, end + 10) },
            ]},
          };
        });
        this.bulkMode = 'annotate';
        this.bulkCandidates = drafts;
        this.bulkChecked = Object.fromEntries(drafts.map(a => [a.id, true]));
        new bootstrap.Modal(document.getElementById('bulkValidateModal')).show();
      },

      confirmBulkAnnotation() {
        const toAdd = this.bulkCandidates.filter(a => this.bulkChecked[a.id]);
        for (const a of toAdd) {
          this.annotations = [...this.annotations, a];
          this.saveAnnotation(a);
        }
        this.bulkCandidates = [];
        bootstrap.Modal.getInstance(document.getElementById('bulkValidateModal'))?.hide();
      },

      // ── Focus-mode: mark current annotation as ATR noise or non-resolv ────────
      _focusMarkAs(bodyUpdates) {
        const cur = this.focusCurrent; if (!cur) return;
        this.focusUnclearOpen = false;
        const updated = { ...cur, resp_id: CURRENT_USER_ID, body: [{ ...cur.body[0], ...bodyUpdates }] };
        this.annotations = this.annotations.map(a => a.id === cur.id ? updated : a);
        this.saveAnnotation(updated);
        this.$nextTick(() => {
          const n = this.focusAnnotations.length;
          if (!n) { this.exitFocusMode(); return; }
          this.focusAnnotIndex = Math.min(this.focusAnnotIndex, n - 1);
          this.focusEditValue  = getBodyValue(this.focusCurrent) ?? '';
          this.refocusFocusInput();
        });
      },
      focusMarkAtrNoise() {
        const cur = this.focusCurrent; if (!cur) return;
        const exact = getExact(cur);
        this._focusMarkAs({ value: exact, purpose: 'atr_noise' });
      },
      focusMarkNonResolvAbbr(reason) {
        const cur = this.focusCurrent; if (!cur) return;
        const exact = getExact(cur);
        this._focusMarkAs({ value: exact, purpose: 'non_resolv_abbr', reason });
      },

      // ── Remove annotation ─────────────────────────────────────────────────────
      removeAnnotation(annot) {
        this.annotations = this.annotations.filter(a => a.id !== annot.id);
        if (this.selectedAnnotationId === annot.id) this.selectedAnnotationId = null;
        this.deleteAnnotation(annot);
        if (this.focusMode) return;
        const similar = findSimilarByExact(this.annotations, annot);
        if (similar.length > 0) {
          this.bulkMode = 'delete';
          this.bulkCandidates = similar;
          this.bulkChecked = Object.fromEntries(similar.map(a => [a.id, true]));
          new bootstrap.Modal(document.getElementById('bulkValidateModal')).show();
        }
      },

      // ── Clear all unvalidated ─────────────────────────────────────────────────
      confirmClearPending() {
        document.getElementById('clearPendingCount').textContent = this.pendingAnnotationsSorted.length;
        const modal = new bootstrap.Modal(document.getElementById('clearPendingModal'));
        document.getElementById('clearPendingConfirm').onclick = () => { modal.hide(); this.clearPending(); };
        modal.show();
      },
      clearPending() {
        this.annotations = this.annotations.filter(a => a.validated_by);
        this.selectedAnnotationId = null;
        this.saveAnnotations();
      },

      // ── Persistent cross-column selection ────────────────────────────────────
      selectAnnotation(annot) {
        this.selectedAnnotationId = this.selectedAnnotationId === annot.id ? null : annot.id;
        if (this.selectedAnnotationId) {
          this.$refs.pageSource.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
          this.$refs.normalizedText.querySelector('[data-annotation].hovered')?.classList.remove('hovered');
          this.hoveredAnnotationId = null;
          this._focusAnnotInput(annot);
        }
      },

      // ── Validate / un-validate ────────────────────────────────────────────────
      validateAnnotation(annot) {
        const updated = { ...annot, validated_by: CURRENT_USER_ID };
        this.annotations = this.annotations.map(a => a.id === annot.id ? updated : a);
        this.saveAnnotation(updated);
        const similar = findSimilarAnnotations(this.annotations, annot);
        if (similar.length > 0) {
          this.bulkMode = 'validate';
          this.bulkCandidates = similar;
          this.bulkChecked = Object.fromEntries(similar.map(a => [a.id, true]));
          new bootstrap.Modal(document.getElementById('bulkValidateModal')).show();
        }
      },
      confirmBulkValidation() {
        const toValidate = new Set(
          Object.entries(this.bulkChecked).filter(([,v]) => v).map(([id]) => id)
        );
        this.annotations = this.annotations.map(a =>
          toValidate.has(a.id) ? {...a, validated_by: CURRENT_USER_ID} : a
        );
        bootstrap.Modal.getInstance(document.getElementById('bulkValidateModal'))?.hide();
        this.bulkCandidates = [];
        this.bulkChecked = {};
        this.bulkMode = 'validate';
        this.saveAnnotations();
      },
      confirmBulkDeletion() {
        const toDelete = new Set(
          Object.entries(this.bulkChecked).filter(([,v]) => v).map(([id]) => id)
        );
        const removed = this.annotations.filter(a => toDelete.has(a.id));
        this.annotations = this.annotations.filter(a => !toDelete.has(a.id));
        bootstrap.Modal.getInstance(document.getElementById('bulkValidateModal'))?.hide();
        this.bulkCandidates = [];
        this.bulkChecked = {};
        this.bulkMode = 'validate';
        removed.forEach(a => this.deleteAnnotation(a));
      },
      unvalidateAnnotation(annot) {
        const { validated_by, ...updated } = annot;
        this.annotations = this.annotations.map(a => a.id === annot.id ? updated : a);
        this.saveAnnotation(updated);
      },

      toggleInsertMode() { this.insertMode = !this.insertMode; if (this.insertMode) this.refineMode = false; },
      toggleRefineMode() { this.refineMode = !this.refineMode; if (this.refineMode) this.insertMode = false; },

      adjustAnnotationBoundary(side, delta, annotId = null) {
        const id  = annotId ?? this.selectedAnnotationId;
        const cur = this.annotations.find(a => a.id === id);
        if (!cur) return;
        const pos = getSelector(cur, 'TextPositionSelector');
        let start = pos.start, end = pos.end;
        if (side === 'start') start += delta;
        else                  end   += delta;
        start = Math.max(0, start);
        end   = Math.min(this.fullText.length, end);
        if (start >= end) return;
        const others = this.annotations.filter(a => a.id !== cur.id && !isInsertion(a));
        if (others.some(a => getStart(a) < end && getEnd(a) > start)) return;
        const t = this.fullText;
        const updated = { ...cur, target: { ...cur.target, selector: [
          { type: 'TextPositionSelector', start, end },
          { type: 'TextQuoteSelector',
            exact:  t.slice(start, end),
            prefix: t.slice(Math.max(0, start - 10), start),
            suffix: t.slice(end, end + 10) },
        ]}};
        this.annotations = this.annotations.map(a => a.id === cur.id ? updated : a);
        this.saveAnnotation(updated);
        if (this.focusMode && this.focusCurrent?.id === id) {
          this.focusEditValue = getBodyValue(updated) ?? '';
        }
      },

      renderVisible(text) {
        return escapeHtml(text ?? '')
          .replace(/ /g, '<span class="tok-ws">·</span>')
          .replace(/\n/g, '<span class="tok-ws">&#8629;</span>');
      },

      startResize(which, evt) {
        const panels = document.getElementById('editor-panels');
        const startX      = evt.clientX;
        const startSrc    = this.sourceWidth;
        const startAnnots = this.annotsWidth;
        const divider = evt.currentTarget;
        divider.classList.add('active');
        const onMove = (e) => {
          const pct = (e.clientX - startX) / panels.offsetWidth * 100;
          if (which === 'source') {
            this.sourceWidth = Math.max(10, Math.min(60, startSrc + pct));
          } else {
            this.annotsWidth = Math.max(10, Math.min(60, startAnnots + pct));
          }
        };
        const onUp = () => {
          divider.classList.remove('active');
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      },

      // ── Tab cycling ───────────────────────────────────────────────────────────
      tabToNext(cur) {
        const all  = this.allAnnotationsSorted;
        const next = all[(all.findIndex(a => a.id === cur.id) + 1) % all.length];
        if (next) { this.selectedAnnotationId = next.id; this._focusAnnotInput(next); }
      },

      _handleKeydown(e) {
        if (this.focusMode) {
          if (e.key === 'Escape') { this.exitFocusMode(); e.preventDefault(); }
          const inp = this.$refs.focusModeInput;
          const inpEl = inp && (Array.isArray(inp) ? inp[0] : inp);
          if (document.activeElement !== inpEl) {
            if (e.key === 'ArrowRight') { this.focusNavigate(1);  e.preventDefault(); }
            if (e.key === 'ArrowLeft')  { this.focusNavigate(-1); e.preventDefault(); }
            if (e.key === 'Tab')        { this.focusNavigate(e.shiftKey ? -1 : 1); e.preventDefault(); }
            if (e.key === 'Enter' && !e.ctrlKey) { this.focusValidateAndAdvance(); e.preventDefault(); }
          }
          return;
        }
        if (e.key === 'Escape' && this.pendingAnnot) { this.cancelPending(); e.preventDefault(); return; }
        if (e.key === 'Enter' && e.ctrlKey && this.bulkCandidates.length > 0) {
          e.preventDefault();
          if (this.bulkMode === 'delete') this.confirmBulkDeletion();
          else this.confirmBulkValidation();
          return;
        }
        if (e.key === 'Enter' && e.ctrlKey && this.selectedAnnotationId) {
          const annot = this.annotations.find(a => a.id === this.selectedAnnotationId);
          if (annot && !annot.validated_by) {
            // Read the current DOM value (user may have typed without blurring) and
            // fold it into the annotation before validating — one PUT instead of three.
            const activeEl = document.activeElement;
            let base = annot;
            if (activeEl?.classList.contains('annot-target') && annot.body?.[0]) {
              const domValue = activeEl.value;
              if (domValue !== (annot.body[0].value ?? '')) {
                base = { ...annot, resp_id: CURRENT_USER_ID, body: [{ ...annot.body[0], value: domValue }] };
                this.annotations = this.annotations.map(a => a.id !== annot.id ? a : base);
              }
            }
            this.validateAnnotation(base);
            e.preventDefault();
            this.$nextTick(() => {
              const sorted = this.allAnnotationsSorted;
              const curIdx = sorted.findIndex(a => a.id === annot.id);
              const nextAfter = sorted.slice(curIdx + 1).find(a => !a.validated_by);
              const fallback = sorted.find(a => !a.validated_by && a.id !== annot.id);
              const target = nextAfter || fallback;
              if (target) {
                this.selectedAnnotationId = target.id;
                this._focusAnnotInput(target);
              }
            });
          }
        }
      },

      // ── Delete line ───────────────────────────────────────────────────────────
      async deleteLine(line, idx) {
        if (!confirm(`Delete line #${idx+1}? Annotations on this line will also be removed.`)) return;
        const r = await fetch(urls.deleteLine.replace('__LINE_ID__', line.id), { method:'POST' });
        if (!r.ok) return;
        let charStart = 0;
        for (let i = 0; i < idx; i++) charStart += this.lines[i].original_text.length + 1;
        const lineLen      = line.original_text.length, charEnd = charStart + lineLen;
        const removedChars = lineLen + (idx < this.lines.length - 1 ? 1 : 0);
        this.annotations = this.annotations
          .filter(a => !(getStart(a) >= charStart && getStart(a) <= charEnd))
          .map(a => {
            const pos = getSelector(a, 'TextPositionSelector');
            if (pos && pos.start > charEnd) { pos.start -= removedChars; pos.end -= removedChars; }
            return a;
          });
        this.lines.splice(idx, 1);
        this.fullText = this.lines.map(l => l.original_text).join('\n');
        await this.saveAnnotations();
      },

      async saveAnnotation(annot) {
        try {
          const r = await fetch(urls.saveAnnotation.replace('__ANN_ID__', annot.id), {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(annot),
          });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          this.saveError = false;
        } catch {
          this.saveError = true;
        }
      },
      async deleteAnnotation(annot) {
        try {
          const r = await fetch(urls.deleteAnnotation.replace('__ANN_ID__', annot.id), {
            method: 'DELETE',
          });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          this.saveError = false;
        } catch {
          this.saveError = true;
        }
      },
      async saveAnnotations() {
        try {
          const r = await fetch(urls.saveAnnotations, {
            method:'PUT', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ annotations: this.annotations }),
          });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          this.saveError = false;
        } catch {
          this.saveError = true;
        }
      },
      async setPageStatus(status) {
        this.pageStatus = status;
        await fetch(urls.pageStatus, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ status }),
        });
      },

      // ── Focus Mode ────────────────────────────────────────────────────────────
      enterFocusMode() {
        if (!this.focusAnnotations.length) return;
        const selIdx = this.selectedAnnotationId
          ? this.focusAnnotations.findIndex(a => a.id === this.selectedAnnotationId)
          : -1;
        this.focusAnnotIndex = selIdx >= 0 ? selIdx : 0;
        this.focusEditValue  = getBodyValue(this.focusCurrent) ?? '';
        this.focusMode = true;
        this.$nextTick(() => this.refocusFocusInput());
      },
      exitFocusMode() {
        this.saveFocusEdit();
        this.focusMode = false;
        this.focusUnclearOpen = false;
      },
      focusNavigate(delta) {
        this.focusUnclearOpen = false;
        this.saveFocusEdit();
        const n = this.focusAnnotations.length;
        if (!n) return;
        this.focusAnnotIndex = (this.focusAnnotIndex + delta + n) % n;
        this.focusEditValue  = getBodyValue(this.focusCurrent) ?? '';
        this.$nextTick(() => this.refocusFocusInput());
      },
      focusJump(idx) {
        this.saveFocusEdit();
        this.focusAnnotIndex = idx;
        this.focusEditValue  = getBodyValue(this.focusCurrent) ?? '';
        this.$nextTick(() => this.refocusFocusInput());
      },
      focusValidateAndAdvance() {
        this.focusUnclearOpen = false;
        const cur = this.focusCurrent; if (!cur) return;
        // Combine pending edit + validation into one PUT
        let updated = cur;
        if (cur.body?.[0] && getBodyValue(cur) !== this.focusEditValue) {
          updated = { ...updated, resp_id: CURRENT_USER_ID, body: [{ ...cur.body[0], value: this.focusEditValue }] };
        }
        updated = { ...updated, validated_by: CURRENT_USER_ID };
        this.annotations = this.annotations.map(a => a.id === cur.id ? updated : a);
        this.focusValidated = true;
        this.saveAnnotation(updated);
        this.$nextTick(() => {
          const n = this.focusAnnotations.length;
          this.focusValidated = false;
          if (!n) { this.exitFocusMode(); return; }
          this.focusAnnotIndex = Math.min(this.focusAnnotIndex, n - 1);
          this.focusEditValue  = getBodyValue(this.focusCurrent) ?? '';
          this.refocusFocusInput();
        });
      },
      focusDelete() {
        this.focusUnclearOpen = false;
        const cur = this.focusCurrent; if (!cur) return;
        this.removeAnnotation(cur);
        this.$nextTick(() => {
          const n = this.focusAnnotations.length;
          if (!n) { this.exitFocusMode(); return; }
          this.focusAnnotIndex = Math.min(this.focusAnnotIndex, n - 1);
          this.focusEditValue  = getBodyValue(this.focusCurrent) ?? '';
          this.refocusFocusInput();
        });
      },
      saveFocusEdit() {
        const cur = this.focusCurrent;
        if (!cur || !cur.body?.[0] || getBodyValue(cur) === this.focusEditValue) return;
        const updated = { ...cur, resp_id: CURRENT_USER_ID, body: [{ ...cur.body[0], value: this.focusEditValue }] };
        this.annotations = this.annotations.map(a => a.id !== cur.id ? a : updated);
        this.saveAnnotation(updated);
      },
      refocusFocusInput() {
        this.$nextTick(() => {
          const inp = this.$refs.focusModeInput;
          const el  = Array.isArray(inp) ? inp[0] : inp;
          el?.focus(); el?.select();
        });
      },
    },
  });
}

// ── Page works helpers (called from onclick in HTML) ──────────────────────────
async function pageAddWork() {
  const title = document.getElementById('page-work-title').value.trim();
  if (!title) return;
  const genre = document.getElementById('page-work-genre').value.trim();
  const resp = await fetch(window.__EDITOR_CONFIG__.urls.addWork, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title, genre}),
  });
  if (!resp.ok) { alert('Failed to add work'); return; }
  const data = await resp.json();
  const work = data.work;
  document.getElementById('page-no-works-label')?.remove();
  const chip = document.createElement('span');
  chip.className = 'badge bg-primary me-1';
  chip.dataset.workId = work.id;
  chip.innerHTML = `${work.title}${work.genre ? ` <em>(${work.genre})</em>` : ''}
    <button type="button" class="btn-close btn-close-white btn-sm ms-1" aria-label="Remove"
            style="font-size:.5em;" onclick="pageRemoveWork(${work.id})"></button>`;
  document.getElementById('page-works-chips').appendChild(chip);
  document.getElementById('page-work-title').value = '';
  document.getElementById('page-work-genre').value = '';
}

async function pageRemoveWork(workId) {
  const url = window.__EDITOR_CONFIG__.urls.removeWork.replace('__WORK_ID__', workId);
  await fetch(url, {method: 'DELETE'});
  document.querySelector(`#page-works-chips [data-work-id="${workId}"]`)?.remove();
  if (!document.querySelectorAll('#page-works-chips .badge').length) {
    const span = document.createElement('span');
    span.className = 'text-muted small';
    span.id = 'page-no-works-label';
    span.textContent = 'None';
    document.getElementById('page-works-chips').appendChild(span);
  }
}

// Expose for onclick= handlers in HTML template
window.pageAddWork    = pageAddWork;
window.pageRemoveWork = pageRemoveWork;

// Auto-mount in browser
if (typeof window !== 'undefined' && window.__EDITOR_CONFIG__) {
  createEditorApp(window.__EDITOR_CONFIG__).mount('#editor-root');
}
