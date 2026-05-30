(function () {
    'use strict';

    const input       = document.getElementById('photoInput');
    const btn         = document.getElementById('btnChangePhoto');
    const img         = document.getElementById('avatarImg');
    const placeholder = document.getElementById('avatarPlaceholder');
    const uploadUrl   = window.__photoUploadUrl;
    const photoUrl    = window.__photoUrl;

    if (!input || !btn) return;

    btn.addEventListener('click', () => input.click());

    input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        if (!file) return;

        btn.disabled = true;
        try {
            const blob = await resizeToSquare(file, 512);
            const fd = new FormData();
            fd.append('photo', blob, 'avatar.jpg');

            const res = await fetch(uploadUrl, { method: 'POST', body: fd });
            const result = await res.json();

            if (result.success) {
                img.src = photoUrl + '?v=' + Date.now();   // bust cached old photo
                img.style.display = '';
                if (placeholder) placeholder.style.display = 'none';
            } else {
                alert(result.error || 'Upload failed. Please try again.');
            }
        } catch (err) {
            alert('Could not upload photo. Please try again.');
        } finally {
            btn.disabled = false;
            input.value = '';   // allow re-selecting the same file
        }
    });

    // Downscale + center-crop to a square JPEG. Applies EXIF orientation when the
    // browser supports it; otherwise falls back to the original file, which the
    // server normalizes (resize + exif_transpose) authoritatively.
    async function resizeToSquare(file, size) {
        if (typeof createImageBitmap !== 'function') return file;

        let bitmap;
        try {
            bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
        } catch (e) {
            return file;
        }

        const side = Math.min(bitmap.width, bitmap.height);
        const sx = (bitmap.width - side) / 2;
        const sy = (bitmap.height - side) / 2;

        const canvas = document.createElement('canvas');
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(bitmap, sx, sy, side, side, 0, 0, size, size);
        if (bitmap.close) bitmap.close();

        return await new Promise(resolve => {
            canvas.toBlob(b => resolve(b || file), 'image/jpeg', 0.85);
        });
    }
})();
