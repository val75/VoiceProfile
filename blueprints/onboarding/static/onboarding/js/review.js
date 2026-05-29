(function () {
    'use strict';

    const CATEGORIES = [
        'construction', 'warehouse', 'food_service', 'driving', 'cleaning',
        'retail', 'admin', 'maintenance', 'general_labor', 'other'
    ];

    const data = window.__profileData || {};
    const reviewUrl = window.__reviewUrl;
    const reExtractUrl = window.__reExtractUrl;

    /* ── DOM refs ──────────────────────────────────────────────────────── */
    const workList         = document.getElementById('workList');
    const summaryInput     = document.getElementById('experienceSummary');
    const shiftSelect      = document.getElementById('shiftPreference');
    const notesInput       = document.getElementById('availabilityNotes');
    const dayCheckboxes    = document.getElementById('dayCheckboxes');
    const statusMsg        = document.getElementById('statusMsg');

    /* ── Work experience rows ─────────────────────────────────────────── */
    const DURATION_UNITS = ['years', 'months', 'weeks'];

    function fieldGroup(labelText, control, extraClass) {
        const group = document.createElement('div');
        group.className = 'field-group' + (extraClass ? ' ' + extraClass : '');
        const label = document.createElement('label');
        label.textContent = labelText;
        group.append(label, control);
        return group;
    }

    function createWorkRow(item) {
        const card = document.createElement('div');
        card.className = 'work-card';

        const typeInput = document.createElement('input');
        typeInput.type = 'text';
        typeInput.className = 'f-type';
        typeInput.placeholder = 'e.g. Auto mechanic';
        typeInput.value = item.work_type || '';

        const catSelect = document.createElement('select');
        catSelect.className = 'f-cat';
        catSelect.innerHTML = '<option value="">Select…</option>' +
            CATEGORIES.map(c =>
                `<option value="${c}"${c === item.category ? ' selected' : ''}>${c.replace('_', ' ')}</option>`
            ).join('');

        // Duration: amount + unit. Falls back to legacy `years` data.
        const durInput = document.createElement('input');
        durInput.type = 'number';
        durInput.className = 'f-dur';
        durInput.min = '0';
        durInput.placeholder = '0';
        durInput.value = (item.duration ?? item.years) ?? '';

        const unitSelect = document.createElement('select');
        unitSelect.className = 'f-unit';
        const unit = item.duration_unit || 'years';
        unitSelect.innerHTML = DURATION_UNITS
            .map(u => `<option value="${u}"${u === unit ? ' selected' : ''}>${u}</option>`)
            .join('');

        const durWrap = document.createElement('div');
        durWrap.className = 'duration-input';
        durWrap.append(durInput, unitSelect);

        const employerInput = document.createElement('input');
        employerInput.type = 'text';
        employerInput.className = 'f-emp';
        employerInput.placeholder = "e.g. Joe's Garage";
        employerInput.value = item.employer || '';

        const contextInput = document.createElement('input');
        contextInput.type = 'text';
        contextInput.className = 'f-ctx';
        contextInput.placeholder = 'e.g. Fixing brakes and engines';
        contextInput.value = item.context || '';

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '×';
        removeBtn.className = 'btn-remove';
        removeBtn.setAttribute('aria-label', 'Remove this work entry');
        removeBtn.addEventListener('click', () => card.remove());

        const header = document.createElement('div');
        header.className = 'work-card-header';
        header.append(removeBtn);

        const grid = document.createElement('div');
        grid.className = 'field-grid';
        grid.append(
            fieldGroup('Type of work', typeInput),
            fieldGroup('Category', catSelect),
            fieldGroup('How long', durWrap),
            fieldGroup('Employer or place', employerInput),
            fieldGroup('What they did', contextInput, 'field-group-full'),
        );

        card.append(header, grid);
        return card;
    }

    function addWork(item) {
        workList.appendChild(createWorkRow(item || {}));
    }

    /* ── Populate form from data ──────────────────────────────────────── */
    function populate(d) {
        summaryInput.value = d.summary || '';

        workList.innerHTML = '';
        (d.work_experience || []).forEach(w => addWork(w));

        // Availability
        const avail = d.availability || {};
        const days = avail.days || [];
        dayCheckboxes.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.checked = days.includes(cb.value);
        });
        shiftSelect.value = avail.shift_preference || '';
        notesInput.value = avail.notes || '';
    }

    /* ── Collect form into JSON ───────────────────────────────────────── */
    function collect() {
        const work_experience = [];
        workList.querySelectorAll('.work-card').forEach(card => {
            const workType = card.querySelector('.f-type').value.trim();
            if (!workType) return;
            const item = { work_type: workType, category: card.querySelector('.f-cat').value };
            const dur = parseInt(card.querySelector('.f-dur').value, 10);
            if (!isNaN(dur)) {
                item.duration = dur;
                item.duration_unit = card.querySelector('.f-unit').value || 'years';
            }
            const employer = card.querySelector('.f-emp').value.trim();
            if (employer) item.employer = employer;
            const context = card.querySelector('.f-ctx').value.trim();
            if (context) item.context = context;
            work_experience.push(item);
        });

        const days = [];
        dayCheckboxes.querySelectorAll('input:checked').forEach(cb => days.push(cb.value));

        const availability = { days };
        if (shiftSelect.value) availability.shift_preference = shiftSelect.value;
        if (notesInput.value.trim()) availability.notes = notesInput.value.trim();

        const result = { work_experience, availability };
        const summary = summaryInput.value.trim();
        if (summary) result.summary = summary;
        return result;
    }

    /* ── Save handler ─────────────────────────────────────────────────── */
    async function save() {
        statusMsg.textContent = 'Saving...';
        statusMsg.className = 'status-msg';

        try {
            const res = await fetch(reviewUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(collect()),
            });
            const result = await res.json();

            if (result.success) {
                window.location.href = result.next_url;
            } else {
                statusMsg.textContent = result.error || 'Save failed.';
                statusMsg.className = 'status-msg error';
            }
        } catch (err) {
            statusMsg.textContent = 'Network error. Please try again.';
            statusMsg.className = 'status-msg error';
        }
    }

    /* ── Re-extract handler ───────────────────────────────────────────── */
    async function reExtract() {
        statusMsg.textContent = 'Re-extracting from transcripts...';
        statusMsg.className = 'status-msg';

        try {
            const res = await fetch(reExtractUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            const result = await res.json();

            if (result.success) {
                populate(result.profile_data);
                statusMsg.textContent = 'Extraction complete. Review the updated data.';
                statusMsg.className = 'status-msg success';
                const banner = document.getElementById('errorBanner');
                if (banner) banner.style.display = 'none';
            } else {
                statusMsg.textContent = result.error || 'Extraction failed.';
                statusMsg.className = 'status-msg error';
            }
        } catch (err) {
            statusMsg.textContent = 'Network error. Please try again.';
            statusMsg.className = 'status-msg error';
        }
    }

    /* ── Wire up events ───────────────────────────────────────────────── */
    document.getElementById('btnAddWork').addEventListener('click', () => addWork());
    document.getElementById('btnSave').addEventListener('click', save);
    document.getElementById('btnReExtractBottom').addEventListener('click', reExtract);

    const btnReExtractTop = document.getElementById('btnReExtract');
    if (btnReExtractTop) btnReExtractTop.addEventListener('click', reExtract);

    /* ── Initial population ───────────────────────────────────────────── */
    populate(data);

})();
