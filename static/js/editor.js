import { createApp } from 'vue';
import {
  getSelector, getStart, getEnd, getExact, getPrefix, getSuffix, getBodyValue,
  isInsertion, isAtrNoise, isSpaceExact,
  escapeHtml, applyAnnotations,
  buildSourceHtml, computeNormalizedPositions, buildNormalizedPageHtml,
  findSimilarAnnotations,
} from './editor-utils.js';

// Module-level pending annotation (raw W3C object, not reactive)
let pendingAnnotRaw = null;

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
        fontSize:            1,
        sourceWidth:         33,
        annotsWidth:         28,
        saveError:           false,
        bulkCandidates:      [],
        bulkChecked:         {},
        showAnnotContext:     false,
      };
    },

    computed: {
      allAnnotationsSorted()       { return [...this.annotations].sort((a,b) => getStart(a)-getStart(b)); },
      pendingAnnotationsSorted()   { return this.allAnnotationsSorted.filter(a => !a.validated_by); },
      validatedAnnotationsSorted() { return this.allAnnotationsSorted.filter(a =>  a.validated_by); },
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
    },
    beforeUnmount() {
      document.removeEventListener('keydown', this._handleKeydown);
    },

    methods: {
      getExact, getPrefix, getSuffix, getBodyValue, isInsertion, isAtrNoise, isSpaceExact,
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
          const start = pr.toString().length;
          const end   = start + range.toString().length;
          if (start === end) return;

          const t      = this.fullText;
          const exact  = t.slice(start, end);
          const prefix = t.slice(Math.max(0, start - 10), start);
          const suffix = t.slice(end, end + 10);

          if (this.refineMode && this.selectedAnnotationId) {
            const tid = this.selectedAnnotationId;
            this.annotations = this.annotations.map(a => a.id !== tid ? a : {
              ...a, target: { ...a.target, selector: [
                { type:'TextPositionSelector', start, end },
                { type:'TextQuoteSelector', exact, prefix, suffix },
              ]},
            });
            this.saveAnnotations();
            this.refineMode = false;
            sel.removeAllRanges();
            return;
          }

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
        this.annotations = this.annotations.map(a =>
          a.id !== annot.id || !a.body?.[0] ? a : { ...a, resp_id: CURRENT_USER_ID, body:[{ ...a.body[0], value:evt.target.value }] }
        );
        this.saveAnnotations();
      },

      // ── Commit pending annotation ─────────────────────────────────────────────
      commitPending(value) {
        if (!pendingAnnotRaw) return;
        const annot = pendingAnnotRaw; pendingAnnotRaw = null; this.pendingAnnot = null;
        const posSel = getSelector(annot, 'TextPositionSelector');
        annot.body   = [{ type:'TextualBody', value: value ?? '',
                          purpose: posSel.start === posSel.end ? 'insertion' : 'normalizing' }];
        annot.resp_id = CURRENT_USER_ID;
        this.annotations = [...this.annotations, annot];
        this.saveAnnotations();
      },

      cancelPending() { pendingAnnotRaw = null; this.pendingAnnot = null; },

      // ── Mark selection as ATR noise ───────────────────────────────────────────
      markAtrNoise() {
        if (!pendingAnnotRaw) return;
        const annot = pendingAnnotRaw; pendingAnnotRaw = null; this.pendingAnnot = null;
        const exact = getSelector(annot, 'TextQuoteSelector').exact ?? '';
        annot.body = [{ type: 'TextualBody', value: exact, purpose: 'atr_noise' }];
        annot.resp_id = CURRENT_USER_ID;
        this.annotations = [...this.annotations, annot];
        this.saveAnnotations();
      },

      // ── Remove annotation ─────────────────────────────────────────────────────
      removeAnnotation(annot) {
        this.annotations = this.annotations.filter(a => a.id !== annot.id);
        if (this.selectedAnnotationId === annot.id) this.selectedAnnotationId = null;
        this.saveAnnotations();
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
        this.annotations = this.annotations.map(a => a.id===annot.id ? {...a, validated_by:CURRENT_USER_ID} : a);
        this.saveAnnotations();
        const similar = findSimilarAnnotations(this.annotations, annot);
        if (similar.length > 0) {
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
        this.saveAnnotations();
      },
      unvalidateAnnotation(annot) {
        this.annotations = this.annotations.map(a => {
          if (a.id !== annot.id) return a;
          const { validated_by, ...rest } = a; return rest;
        });
        this.saveAnnotations();
      },

      toggleInsertMode() { this.insertMode = !this.insertMode; if (this.insertMode) this.refineMode = false; },
      toggleRefineMode() { this.refineMode = !this.refineMode; if (this.refineMode) this.insertMode = false; },

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
        if (e.key === 'Escape' && this.pendingAnnot) { this.cancelPending(); e.preventDefault(); return; }
        if (e.key === 'Enter' && e.ctrlKey && this.bulkCandidates.length > 0) {
          e.preventDefault();
          this.confirmBulkValidation();
          return;
        }
        if (e.key === 'Enter' && e.ctrlKey && this.selectedAnnotationId) {
          const annot = this.annotations.find(a => a.id === this.selectedAnnotationId);
          if (annot && !annot.validated_by) {
            document.activeElement?.blur();
            this.validateAnnotation(annot);
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
