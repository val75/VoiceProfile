let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];

recordingIndicator.style.display = "block";   // when recording
recordingIndicator.style.display = "none";    // when stopped

document.addEventListener("DOMContentLoaded", () => {
  const recordBtn = document.getElementById("recordBtn");
  const stopBtn = document.getElementById("stopBtn");
  const sendBtn = document.getElementById("sendBtn");
  const transcriptEl = document.getElementById("transcript");

  const transcriptionBox = document.getElementById("transcriptionBox");

  const confirmationSection = document.getElementById("confirmationSection");
  const confirmationText = document.getElementById("confirmationText");
  const confirmYes = document.getElementById("confirmYes");
  const confirmNo = document.getElementById("confirmNo");

  recordBtn.onclick = async () => {
    audioChunks = [];

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaStream = stream;

    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
      mediaStream.getTracks().forEach(t => t.stop());
      recordBtn.disabled = false;
      stopBtn.disabled = true;
    };

    mediaRecorder.start();
    recordBtn.disabled = true;
    stopBtn.disabled = false;
  };

  stopBtn.onclick = () => {
    mediaRecorder.stop();
  };

  sendBtn.onclick = async () => {
    const blob = new Blob(audioChunks, { type: "audio/webm" });
    const formData = new FormData();
    formData.append("audio", blob, "voice.webm");

    const response = await fetch(
      `/onboarding/${PROFILE_ID}/name/transcribe`,
      {
        method: "POST",
        body: formData
      }
    );

    const data = await response.json();

    // transcriptEl.innerText = data.transcript;
    transcriptionBox.innerText = data.name;

    // 🔥 SHOW CONFIRMATION SECTION HERE
    if (data.needs_confirmation) {
        confirmationSection.style.display = "block";
        confirmationText.innerText = `Is your name ${data.name}?`;

        // Disable recording while confirming
        recordBtn.disabled = true;
        stopBtn.disabled = true;
        sendBtn.disabled = true;
    }

    // Auto-advance to next step
    if (data.next_step) {
      window.location.href = `/onboarding/${PROFILE_ID}/${data.next_step}`;
    }
  };

  confirmYes.onclick = async () => {
    const response = await fetch(`/onboarding/${PROFILE_ID}/name/confirm`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ confirmed: true })
    });

    const data = await response.json();

    if (data.next_url) {
        window.location.href = data.next_url;
    }
  };

  confirmNo.onclick = async () => {
    await fetch(`/onboarding/${PROFILE_ID}/name/confirm`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ confirmed: false })
    });

    // Reset UI
    confirmationSection.style.display = "none";
    transcriptionBox.innerText = "Please record your name again.";

    recordBtn.disabled = false;
    stopBtn.disabled = true;
    sendBtn.disabled = true;
  };
});
