// Shared metadata modal — one DOM instance per page (#metaModal), reused for
// editing a Folder, a Document, or a Part. Which field groups are visible is
// decided per-call by which keys are present in config.fields; the only
// field whose backend name varies (Folder uses "name", Document uses
// "label") is handled separately via config.title.
(function () {
  function $(id) { return document.getElementById(id); }

  const FIELD_KEYS = ['description', 'language', 'status', 'qid', 'iiif_manifest_url', 'original_filename'];

  const MetadataModal = {
    _works: null,
    _worksAddUrl: null,
    _worksRemoveUrlTemplate: null,
    _titleField: null,

    open(config) {
      const modalEl = $('metaModal');
      const form = $('metaForm');

      $('metaModalTitleText').textContent = config.title || '';

      // ── Title field (name="name" for Folder, name="label" for Document) ──
      const titleGroup = form.querySelector('[data-field-group="title"]');
      const titleInput = $('metaTitleInput');
      if (config.titleField) {
        titleGroup.style.display = '';
        $('metaTitleLabel').textContent = config.titleLabel || 'Name';
        titleInput.value = config.titleValue ?? '';
        titleInput.required = true;
        this._titleField = config.titleField;
      } else {
        titleGroup.style.display = 'none';
        titleInput.required = false;
        this._titleField = null;
      }

      // ── Generic fields ──
      for (const key of FIELD_KEYS) {
        const groupEls = form.querySelectorAll(`[data-field-group="${key}"]`);
        const show = !!(config.fields && key in config.fields);
        groupEls.forEach(el => el.style.display = show ? '' : 'none');
        if (!show) continue;
        const input = form.elements[key];
        if (key === 'language' && config.languages) {
          input.innerHTML = config.languages.map(([c, l]) => `<option value="${c}">${l}</option>`).join('');
        }
        input.value = config.fields[key] ?? '';
      }
      form.querySelectorAll('[data-field-label]').forEach(lbl => {
        const key = lbl.dataset.fieldLabel;
        if (config.fieldLabels && config.fieldLabels[key]) lbl.textContent = config.fieldLabels[key];
      });

      form.onsubmit = async (e) => {
        e.preventDefault();
        const body = {};
        if (this._titleField) body[this._titleField] = titleInput.value;
        for (const key of FIELD_KEYS) {
          if (config.fields && key in config.fields) body[key] = form.elements[key].value;
        }
        const r = await fetch(config.updateUrl, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r.ok) { alert('Failed to save metadata'); return; }
        const data = await r.json().catch(() => ({}));
        if (config.onSaved) config.onSaved(data);
        else window.location.reload();
      };

      // ── Works ──
      const worksGroup = document.querySelector('#metaModal [data-field-group="works"]');
      worksGroup.style.display = config.works ? '' : 'none';
      if (config.works) {
        this._works = config.works.slice();
        this._worksAddUrl = config.worksAddUrl;
        this._worksRemoveUrlTemplate = config.worksRemoveUrlTemplate;
        this._renderWorks();
        $('metaWorkTitle').value = '';
        $('metaWorkGenre').value = '';
        $('metaWorkAddBtn').onclick = async () => {
          const title = $('metaWorkTitle').value.trim();
          if (!title) return;
          const genre = $('metaWorkGenre').value.trim();
          const r = await fetch(this._worksAddUrl, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, genre }),
          });
          if (!r.ok) { alert('Failed to add work'); return; }
          const data = await r.json();
          this._works.push(data.work);
          this._renderWorks();
          $('metaWorkTitle').value = '';
          $('metaWorkGenre').value = '';
        };
      }

      // ── Move ──
      const moveGroup = document.querySelector('#metaModal [data-field-group="move"]');
      moveGroup.style.display = config.move ? '' : 'none';
      if (config.move) {
        $('metaMoveLabel').textContent = config.move.label || 'Move';
        const select = $('metaMoveTarget');
        select.innerHTML = '<option value="">Loading…</option>';
        fetch(config.move.targetsUrl).then(r => r.json()).then(items => {
          const others = items.filter(i => i.id !== config.move.currentId);
          select.innerHTML = others.length
            ? others.map(i => `<option value="${i.id}">${i.name}</option>`).join('')
            : '<option value="">No other options available</option>';
        });
        $('metaMoveBtn').onclick = async () => {
          const targetId = select.value;
          if (!targetId) return;
          const body = {};
          body[config.move.bodyKey] = Number(targetId);
          const r = await fetch(config.move.submitUrl, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
          if (!r.ok) { alert('Failed to move'); return; }
          if (config.move.onMoved) config.move.onMoved(targetId);
          else window.location.reload();
        };
      }

      // ── Reprocess ──
      const reprocessGroup = document.querySelector('#metaModal [data-field-group="reprocess"]');
      reprocessGroup.style.display = config.reprocess ? '' : 'none';
      if (config.reprocess) {
        const btn = $('metaReprocessBtn');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-arrows-rotate me-1"></i>Reprocess';
        btn.onclick = async () => {
          if (!confirm('Re-run normalization on this document? This replaces its current annotations.')) return;
          btn.disabled = true;
          btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Queuing…';
          const r = await fetch(config.reprocess.url, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config.reprocess.body || {}),
          });
          if (!r.ok) {
            alert(r.status === 409 ? 'Already processing — wait for it to finish first.' : 'Failed to queue reprocessing');
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-arrows-rotate me-1"></i>Reprocess';
            return;
          }
          if (config.reprocess.onQueued) config.reprocess.onQueued();
          else window.location.reload();
        };
      }

      // ── Delete ──
      const deleteGroup = document.querySelector('#metaModal [data-field-group="delete"]');
      deleteGroup.style.display = config.delete ? '' : 'none';
      if (config.delete) {
        $('metaDeleteLink').href = config.delete.url;
        $('metaDeleteLabel').textContent = config.delete.label || 'Delete';
      }

      new bootstrap.Modal(modalEl).show();
    },

    _renderWorks() {
      const chips = $('metaWorksChips');
      if (!this._works.length) {
        chips.innerHTML = '<span class="text-muted small">No works linked yet.</span>';
        return;
      }
      chips.innerHTML = this._works.map(w => `
        <span class="badge bg-primary me-1 mb-1" style="font-size:.85em;">
          ${w.title}${w.genre ? ` <em>(${w.genre})</em>` : ''}
          <button type="button" class="btn-close btn-close-white btn-sm ms-1" style="font-size:.5em;"
                  onclick="MetadataModal._removeWork(${w.id})"></button>
        </span>`).join('');
    },

    async _removeWork(workId) {
      if (!this._worksRemoveUrlTemplate) return;
      const url = this._worksRemoveUrlTemplate.replace('__WORK_ID__', workId);
      const r = await fetch(url, { method: 'DELETE' });
      if (!r.ok) { alert('Failed to remove work'); return; }
      this._works = this._works.filter(w => w.id !== workId);
      this._renderWorks();
    },
  };

  window.MetadataModal = MetadataModal;
})();
