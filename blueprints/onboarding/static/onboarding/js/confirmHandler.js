/**
 * confirmHandler.js
 * Boots VoiceRecorder and manages the post-transcription confirmation panel:
 * That's right / Edit / Re-record, all available from the first attempt.
 *
 * Expects the following in the DOM:
 *   #questionId      - hidden field with the question key
 *   #transcribeUrl   - hidden field with the profile-scoped transcribe endpoint
 *   #status          - status message element
 *   #controls / #recordBtn / #recordIcon / #recordLabel / #againBtn
 *   #timer / #visualizer / .bar
 *   #confirmPanel    - confirmation panel wrapper
 *   #heardLabel      - label above transcription text
 *   #heardText       - element that displays the transcription
 *   #btnConfirm      - confirm button
 *   #btnEdit         - edit button
 *   #btnRetry        - re-record / cancel button
 */

(function () {
    'use strict';

    function init() {
        /* ── DOM refs ──────────────────────────────────────────────────── */
        const statusEl     = document.getElementById('status');
        const confirmPanel = document.getElementById('confirmPanel');
        const heardLabel   = document.getElementById('heardLabel');
        const heardText    = document.getElementById('heardText');
        const btnConfirm   = document.getElementById('btnConfirm');
        const btnEdit      = document.getElementById('btnEdit');
        const btnRetry     = document.getElementById('btnRetry');

        /* ── State ────────────────────────────────────────────────────── */
        const questionId   = document.getElementById('questionId').value;
        const isName       = questionId === 'name';
        let confirmUrl          = null;
        let isEditing           = false;
        let currentTranscription = '';

        /* ── Helpers ──────────────────────────────────────────────────── */
        function showConfirmPanel(text) {
            heardText.textContent = text;
            // Story and availability are sentences: show them as a readable,
            // scrollable paragraph instead of one big bold line.
            heardText.classList.toggle('long', !isName);
            btnEdit.hidden = false;
            confirmPanel.classList.add('visible');
        }

        function hideConfirmPanel() {
            confirmPanel.classList.remove('visible');
            heardText.textContent = '';
            confirmUrl = null;
            isEditing = false;
            btnConfirm.textContent = "✓ That's right";
            btnRetry.textContent = '↩ Re-record';
            heardLabel.textContent = 'We heard';
        }

        function setConfirmBtnsDisabled(disabled) {
            btnConfirm.disabled = disabled;
            btnRetry.disabled   = disabled;
            btnEdit.disabled    = disabled;
        }

        function enterEditMode() {
            isEditing = true;

            const input = isName
                ? document.createElement('input')
                : document.createElement('textarea');

            input.id = 'editInput';
            input.value = currentTranscription;
            input.className = 'edit-input';
            if (!isName) {
                input.rows = questionId === 'story' ? 10 : 4;
            }

            // The textarea is its own box; drop the reading-box styling around it.
            heardText.classList.remove('long');
            heardText.textContent = '';
            heardText.appendChild(input);
            input.focus();
            if (isName) {
                input.select();
            }

            heardLabel.textContent = 'Edit below';
            // "That's right" reads as approving the text above; while editing
            // the button saves the edit and moves on, so say that.
            btnConfirm.textContent = '✓ Save and continue';
            btnRetry.textContent = '✕ Cancel';
            btnEdit.hidden = true;
        }

        function exitEditMode() {
            isEditing = false;
            heardText.textContent = currentTranscription;
            heardText.classList.toggle('long', !isName);
            heardLabel.textContent = 'We heard';
            btnConfirm.textContent = "✓ That's right";
            btnRetry.textContent = '↩ Re-record';
            btnEdit.hidden = false;
        }

        /* ── Boot VoiceRecorder ────────────────────────────────────────── */
        const elements = {
            status:      statusEl,
            controls:    document.getElementById('controls'),
            recordBtn:   document.getElementById('recordBtn'),
            recordIcon:  document.getElementById('recordIcon'),
            recordLabel: document.getElementById('recordLabel'),
            againBtn:    document.getElementById('againBtn'),
            timer:       document.getElementById('timer'),
            visualizer:  document.getElementById('visualizer'),
            bars:        document.querySelectorAll('.bar')
        };

        if (typeof window.VoiceRecorder === 'undefined') {
            console.error('VoiceRecorder class not found.');
            statusEl.textContent = 'Error: Required scripts not loaded';
            statusEl.className = 'error';
            return;
        }

        const recorder = new window.VoiceRecorder(elements, {
            onSuccess(data) {
                confirmUrl = data.confirm_url || null;

                const displayText = data.name || data.transcription;

                if (confirmUrl && displayText) {
                    currentTranscription = displayText;
                    statusEl.textContent = 'Does this look right?';
                    statusEl.className = '';
                    showConfirmPanel(displayText);
                } else {
                    // No confirmation step — default display
                    recorder.reset();
                    statusEl.textContent = data.text
                        ? `Transcription: "${data.text}"`
                        : 'Transcription complete';
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
                recorder.reset();
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
