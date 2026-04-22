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
    const skillsList       = document.getElementById('skillsList');
    const rolesList        = document.getElementById('rolesList');
    const totalYearsInput  = document.getElementById('totalYears');
    const summaryInput     = document.getElementById('experienceSummary');
    const shiftSelect      = document.getElementById('shiftPreference');
    const notesInput       = document.getElementById('availabilityNotes');
    const dayCheckboxes    = document.getElementById('dayCheckboxes');
    const statusMsg        = document.getElementById('statusMsg');

    /* ── Skill rows ───────────────────────────────────────────────────── */
    function createSkillRow(skill) {
        const row = document.createElement('div');
        row.className = 'item-row';

        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.placeholder = 'Skill name';
        nameInput.value = skill.name || '';
        nameInput.className = 'input-med';

        const catSelect = document.createElement('select');
        catSelect.className = 'input-sm';
        catSelect.innerHTML = '<option value="">Category</option>' +
            CATEGORIES.map(c =>
                `<option value="${c}"${c === skill.category ? ' selected' : ''}>${c.replace('_', ' ')}</option>`
            ).join('');

        const yearsInput = document.createElement('input');
        yearsInput.type = 'number';
        yearsInput.placeholder = 'Yrs';
        yearsInput.min = '0';
        yearsInput.max = '99';
        yearsInput.value = skill.years_experience ?? '';
        yearsInput.className = 'input-xs';

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '\u00d7';
        removeBtn.className = 'btn-remove';
        removeBtn.addEventListener('click', () => row.remove());

        row.append(nameInput, catSelect, yearsInput, removeBtn);
        return row;
    }

    function addSkill(skill) {
        skillsList.appendChild(createSkillRow(skill || {}));
    }

    /* ── Role rows ────────────────────────────────────────────────────── */
    function createRoleRow(role) {
        const row = document.createElement('div');
        row.className = 'item-row role-row';

        const titleInput = document.createElement('input');
        titleInput.type = 'text';
        titleInput.placeholder = 'Job title';
        titleInput.value = role.title || '';
        titleInput.className = 'input-med';

        const employerInput = document.createElement('input');
        employerInput.type = 'text';
        employerInput.placeholder = 'Employer';
        employerInput.value = role.employer || '';
        employerInput.className = 'input-med';

        const durationInput = document.createElement('input');
        durationInput.type = 'text';
        durationInput.placeholder = 'Duration';
        durationInput.value = role.duration || '';
        durationInput.className = 'input-sm';

        const descInput = document.createElement('input');
        descInput.type = 'text';
        descInput.placeholder = 'Description';
        descInput.value = role.description || '';
        descInput.className = 'input-full';

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '\u00d7';
        removeBtn.className = 'btn-remove';
        removeBtn.addEventListener('click', () => row.remove());

        row.append(titleInput, employerInput, durationInput, descInput, removeBtn);
        return row;
    }

    function addRole(role) {
        rolesList.appendChild(createRoleRow(role || {}));
    }

    /* ── Populate form from data ──────────────────────────────────────── */
    function populate(d) {
        // Skills
        skillsList.innerHTML = '';
        (d.skills || []).forEach(s => addSkill(s));

        // Experience
        const exp = d.experience || {};
        totalYearsInput.value = exp.total_years ?? '';
        summaryInput.value = exp.summary || '';
        rolesList.innerHTML = '';
        (exp.roles || []).forEach(r => addRole(r));

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
        const skills = [];
        skillsList.querySelectorAll('.item-row').forEach(row => {
            const inputs = row.querySelectorAll('input, select');
            const name = inputs[0].value.trim();
            if (!name) return;
            const skill = { name, category: inputs[1].value };
            const yrs = parseInt(inputs[2].value, 10);
            if (!isNaN(yrs)) skill.years_experience = yrs;
            skills.push(skill);
        });

        const roles = [];
        rolesList.querySelectorAll('.item-row').forEach(row => {
            const inputs = row.querySelectorAll('input');
            const title = inputs[0].value.trim();
            if (!title) return;
            roles.push({
                title,
                employer: inputs[1].value.trim(),
                duration: inputs[2].value.trim(),
                description: inputs[3].value.trim(),
            });
        });

        const totalYears = parseInt(totalYearsInput.value, 10);
        const experience = { roles, summary: summaryInput.value.trim() };
        if (!isNaN(totalYears)) experience.total_years = totalYears;

        const days = [];
        dayCheckboxes.querySelectorAll('input:checked').forEach(cb => days.push(cb.value));

        const availability = { days };
        if (shiftSelect.value) availability.shift_preference = shiftSelect.value;
        if (notesInput.value.trim()) availability.notes = notesInput.value.trim();

        return { skills, experience, availability };
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
    document.getElementById('btnAddSkill').addEventListener('click', () => addSkill());
    document.getElementById('btnAddRole').addEventListener('click', () => addRole());
    document.getElementById('btnSave').addEventListener('click', save);
    document.getElementById('btnReExtractBottom').addEventListener('click', reExtract);

    const btnReExtractTop = document.getElementById('btnReExtract');
    if (btnReExtractTop) btnReExtractTop.addEventListener('click', reExtract);

    /* ── Initial population ───────────────────────────────────────────── */
    populate(data);

})();
