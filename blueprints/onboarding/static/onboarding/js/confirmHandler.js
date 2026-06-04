/**
 * confirmHandler.js
 * Boots VoiceRecorder and manages the post-transcription confirmation panel.
 * After 2+ transcription attempts, offers a manual edit option.
 *
 * Expects the following in the DOM:
 *   #questionId      - hidden field with the question key
 *   #transcribeUrl   - hidden field with the profile-scoped transcribe endpoint
 *   #status          - status message element
 *   #record / #stop / #send / #timer / #recordText / #visualizer / .bar
 *   #confirmPanel    - confirmation panel wrapper
 *   #heardLabel      - label above transcription text
 *   #heardName       - element that displays the transcription
 *   #btnConfirm      - confirm button
 *   #btnEdit         - edit button (hidden until attempt >= 2)
 *   #btnRetry        - re-record / cancel button
 */

(function () {
    'use strict';

    function init() {
        /* ── DOM refs ──────────────────────────────────────────────────── */
        const statusEl     = document.getElementById('status');
        const confirmPanel = document.getElementById('confirmPanel');
        const heardLabel   = document.getElementById('heardLabel');
        const heardName    = document.getElementById('heardName');
        const btnConfirm   = document.getElementById('btnConfirm');
        const btnEdit      = document.getElementById('btnEdit');
        const btnRetry     = document.getElementById('btnRetry');

        /* ── State ────────────────────────────────────────────────────── */
        const questionId   = document.getElementById('questionId').value;
        const isStoryStep  = questionId === 'story';
        let confirmUrl          = null;
        let attemptCount        = 0;
        let isEditing           = false;
        let currentTranscription = '';

        /* Format an "MM:SS" timer string as e.g. "1m 34s" / "42s" / "3m". */
        function formatDuration(mmss) {
            const m = parseInt(mmss.slice(0, 2), 10);
            const s = parseInt(mmss.slice(3, 5), 10);
            if (!Number.isFinite(m) || !Number.isFinite(s)) return mmss;
            if (m === 0) return `${s}s`;
            if (s === 0) return `${m}m`;
            return `${m}m ${s}s`;
        }

        /* ── Helpers ──────────────────────────────────────────────────── */
        function showConfirmPanel(text) {
            heardName.textContent = text;
            confirmPanel.classList.add('visible');
        }

        function hideConfirmPanel() {
            confirmPanel.classList.remove('visible');
            heardName.textContent = '';
            confirmUrl = null;
            isEditing = false;
            btnRetry.textContent = '↩ Re-record';
            btnEdit.style.display = 'none';
            heardLabel.textContent = 'We heard';
        }

        function setConfirmBtnsDisabled(disabled) {
            btnConfirm.disabled = disabled;
            btnRetry.disabled   = disabled;
            btnEdit.disabled    = disabled;
        }

        function enterEditMode() {
            isEditing = true;
            const questionId = document.getElementById('questionId').value;
            const isName = questionId === 'name';

            const input = isName
                ? document.createElement('input')
                : document.createElement('textarea');

            input.id = 'editInput';
            input.value = currentTranscription;
            input.className = 'edit-input';
            if (!isName) {
                input.rows = 3;
            }

            heardName.textContent = '';
            heardName.appendChild(input);
            input.focus();
            input.select();

            heardLabel.textContent = 'Edit below';
            btnRetry.textContent = '✕ Cancel';
            btnEdit.style.display = 'none';
        }

        function exitEditMode() {
            isEditing = false;
            heardName.textContent = currentTranscription;
            heardLabel.textContent = 'We heard';
            btnRetry.textContent = '↩ Re-record';
            btnEdit.style.display = attemptCount >= 2 ? '' : 'none';
        }

        /* ── Boot VoiceRecorder ────────────────────────────────────────── */
        const elements = {
            status:     statusEl,
            recordBtn:  document.getElementById('record'),
            stopBtn:    document.getElementById('stop'),
            sendBtn:    document.getElementById('send'),
            timer:      document.getElementById('timer'),
            recordText: document.getElementById('recordText'),
            visualizer: document.getElementById('visualizer'),
            bars:       document.querySelectorAll('.bar')
        };

        if (typeof window.VoiceRecorder === 'undefined') {
            console.error('VoiceRecorder class not found.');
            statusEl.textContent = 'Error: Required scripts not loaded';
            statusEl.className = 'error';
            return;
        }

        new window.VoiceRecorder(elements, {
            onSuccess(data) {
                attemptCount++;
                confirmUrl = data.confirm_url || null;

                const displayText = data.name || data.transcription;

                // Story step: a 3-min transcript is too long to confirm
                // by reading. Show a duration preview + Continue / Re-record.
                if (isStoryStep && confirmUrl && displayText) {
                    currentTranscription = displayText;
                    const captured = formatDuration(elements.timer.textContent);
                    heardLabel.textContent = 'Captured';
                    btnConfirm.textContent = 'Continue';
                    btnEdit.style.display = 'none';
                    statusEl.textContent = '';
                    showConfirmPanel(captured);
                    return;
                }

                if (confirmUrl && displayText) {
                    currentTranscription = displayText;
                    statusEl.textContent = 'Does this look right?';
                    showConfirmPanel(displayText);
                    btnEdit.style.display = attemptCount >= 2 ? '' : 'none';
                } else {
                    // No confirmation step — default display
                    statusEl.textContent = data.text
                        ? `Transcription: "${data.text}"`
                        : 'Transcription complete';
                    elements.sendBtn.disabled = false;
                }
            }
        });

        /* ── Confirm button ────────────────────────────────────────────── */
        btnConfirm.addEventListener('click', async function () {
            if (!confirmUrl) return;

            if (isEditing) {
                const input = document.getElementById('editInput');
                const editedText = (input?.value || '').trim();
                if (!editedText) {
                    statusEl.textContent = 'Please enter some text or cancel editing.';
                    return;
                }
            }

            setConfirmBtnsDisabled(true);

            const isLastStep = document.getElementById('isLastStep')?.value === 'true';
            let loadingTimer = null;
            if (isLastStep) {
                let dots = 0;
                loadingTimer = setInterval(() => {
                    dots = (dots + 1) % 4;
                    statusEl.textContent = 'Building your profile' + '.'.repeat(dots);
                }, 400);
            } else {
                statusEl.textContent = 'Saving…';
            }

            const payload = { confirmed: true };
            if (isEditing) {
                payload.edited_text = document.getElementById('editInput').value.trim();
            }

            try {
                const res  = await fetch(confirmUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                clearInterval(loadingTimer);
                const data = await res.json();

                if (data.next_url) {
                    window.location.href = data.next_url;
                } else {
                    statusEl.textContent = 'Saved!';
                }
            } catch (err) {
                clearInterval(loadingTimer);
                statusEl.textContent = 'Network error. Please try again.';
                setConfirmBtnsDisabled(false);
            }
        });

        /* ── Edit button ───────────────────────────────────────────────── */
        btnEdit.addEventListener('click', function () {
            enterEditMode();
        });

        /* ── Re-record / Cancel button ─────────────────────────────────── */
        btnRetry.addEventListener('click', async function () {
            if (!confirmUrl) return;

            // In edit mode, cancel returns to the confirm panel
            if (isEditing) {
                exitEditMode();
                return;
            }

            // Re-record: POST to wipe backend state, then reset UI in-place
            setConfirmBtnsDisabled(true);
            statusEl.textContent = 'Resetting…';

            try {
                await fetch(confirmUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ confirmed: false })
                });

                hideConfirmPanel();
                statusEl.textContent = 'Ready to record';
                elements.recordBtn.disabled = false;
                elements.sendBtn.disabled = true;
                setConfirmBtnsDisabled(false);
            } catch (err) {
                statusEl.textContent = 'Network error. Please try again.';
                setConfirmBtnsDisabled(false);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
