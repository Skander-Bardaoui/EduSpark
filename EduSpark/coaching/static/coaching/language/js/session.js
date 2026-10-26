import { AudioCapture } from './audio-capture.js';
import { RealtimeTranscriber } from './transcription.js';
import { ExaminerAudio } from './tts.js';
import { configUrl } from './config.js';
import { csrfHeaders } from './csrf.js';

const page = document.querySelector('[data-session-page]');

const STATUS_LABELS = {
  idle: 'inactif',
  requesting: 'demande en cours',
  connecting: 'connexion…',
  connected: 'connecté',
  active: 'actif',
  loading: 'chargement…',
  playing: 'lecture…',
  error: 'erreur',
};

function statusLabel(status) {
  return STATUS_LABELS[status] || status;
}

if (page) {
  const sessionId = page.dataset.sessionId;
  const sessionLanguage = page.dataset.language || 'en';
  const sessionLocale = page.dataset.languageLocale || 'en-US';
  const workletUrl = page.dataset.workletUrl;

  const connectButton = document.getElementById('connect-btn');
  const disconnectButton = document.getElementById('disconnect-btn');
  const sendButton = document.getElementById('send-llm-btn');
  const speakButton = document.getElementById('speak-btn');
  const endButton = document.getElementById('end-session-btn');
  const micStatus = document.getElementById('mic-status');
  const transcriptionStatus = document.getElementById('transcription-status');
  const audioStatus = document.getElementById('audio-status');
  const errorElement = document.getElementById('session-error');
  const liveTranscript = document.getElementById('live-transcript');
  const committedList = document.getElementById('committed-list');
  const committedEmpty = document.getElementById('committed-empty');
  const examinerTextElement = document.getElementById('examiner-text');

  const history = [];
  const transcript = [];
  const pendingSegments = [];

  let examinerText = '';
  let isSending = false;
  let isOpening = false;
  let openingLoaded = false;
  let isEvaluating = false;

  function showError(message) {
    if (!message) {
      return;
    }
    errorElement.textContent = message;
    errorElement.classList.remove('hidden');
  }

  function clearError() {
    errorElement.textContent = '';
    errorElement.classList.add('hidden');
  }

  function updateButtons() {
    const connecting =
      audio.status === 'requesting' || transcription.status === 'connecting';
    const connected = transcription.status === 'connected';
    const idle = audio.status === 'idle' && transcription.status === 'idle';

    connectButton.disabled = isEvaluating || connecting || connected;
    disconnectButton.disabled = isEvaluating || idle;
    sendButton.disabled =
      isEvaluating || isSending || isOpening || pendingSegments.length === 0;
    speakButton.disabled =
      isEvaluating ||
      isOpening ||
      !examinerText ||
      examinerAudio.status === 'loading' ||
      examinerAudio.status === 'playing';
    endButton.disabled =
      isEvaluating ||
      isOpening ||
      !transcript.some((entry) => entry.speaker === 'user');

    connectButton.textContent = connecting ? 'Connexion…' : 'Connecter le micro';
    sendButton.textContent = isSending ? 'Envoi…' : 'Envoyer la réponse';
    speakButton.textContent =
      examinerAudio.status === 'playing' ? 'Lecture…' : 'Écouter l’examinateur';
    endButton.textContent = isEvaluating ? 'Évaluation…' : 'Terminer la session';
  }

  const transcription = new RealtimeTranscriber({
    language: sessionLanguage,
    tokenUrl: configUrl('sttTokenUrl'),
    onStatusChange: (status) => {
      transcriptionStatus.textContent = statusLabel(status);
      updateButtons();
    },
    onPartial: (text) => {
      liveTranscript.textContent = text || '—';
    },
    onCommitted: (text) => {
      pendingSegments.push(text);
      transcript.push({ speaker: 'user', text, timestamp: Date.now() });

      const item = document.createElement('li');
      item.textContent = text;
      committedList.appendChild(item);
      committedEmpty.classList.add('hidden');
      committedList.classList.remove('hidden');

      clearError();
      updateButtons();
    },
    onError: showError,
  });

  const audio = new AudioCapture({
    workletUrl,
    onChunk: (chunk) => transcription.sendAudioChunk(chunk),
    onStatusChange: (status) => {
      micStatus.textContent = statusLabel(status);
      updateButtons();
    },
    onError: showError,
  });

  const examinerAudio = new ExaminerAudio({
    language: sessionLanguage,
    locale: sessionLocale,
    ttsUrl: configUrl('ttsUrl'),
    onStatusChange: (status) => {
      audioStatus.textContent = statusLabel(status);
      updateButtons();
    },
    onError: showError,
  });

  async function handleConnect() {
    clearError();
    try {
      const sampleRate = await audio.start();
      await transcription.connect(sampleRate);
    } catch (error) {
      console.error('[session] connect failed:', error);
    }
  }

  function handleDisconnect() {
    transcription.disconnect();
    audio.stop();
  }

  async function streamExaminer(body) {
    const response = await fetch(configUrl('replyUrl'), {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      credentials: 'same-origin',
      body: JSON.stringify(body),
    });

    if (response.status === 401) {
      window.location.href = configUrl('loginUrl');
      throw new Error('unauthorized');
    }

    if (!response.ok || !response.body) {
      throw new Error('examiner_request_failed');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let reply = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      reply += decoder.decode(value, { stream: true });
      examinerText = reply;
      examinerTextElement.textContent = reply || '—';
    }

    return reply;
  }

  async function loadOpeningQuestion() {
    if (openingLoaded || isOpening) {
      return;
    }

    isOpening = true;
    examinerText = '';
    examinerTextElement.textContent = 'Préparation de la première question de l’examinateur…';
    clearError();
    updateButtons();

    try {
      const reply = (await streamExaminer({ sessionId, opening: true })).trim();
      if (!reply) {
        showError('L’examinateur n’a pas pu démarrer la session. Rechargez la page pour réessayer.');
        return;
      }

      examinerText = reply;
      examinerTextElement.textContent = reply;
      history.push({ role: 'assistant', content: reply });
      transcript.push({
        speaker: 'assistant',
        text: reply,
        timestamp: Date.now(),
      });
      openingLoaded = true;
    } catch (error) {
      console.error('[session] opening question failed:', error);
      showError('L’examinateur n’a pas pu démarrer la session. Rechargez la page pour réessayer.');
    } finally {
      isOpening = false;
      updateButtons();
    }
  }

  async function handleSend() {
    const segment = pendingSegments.join(' ').trim();
    if (!segment || isSending || isOpening) {
      return;
    }

    isSending = true;
    examinerText = '';
    examinerTextElement.textContent = '—';
    clearError();
    updateButtons();

    try {
      const reply = (
        await streamExaminer({ sessionId, transcript: segment, history })
      ).trim();
      if (!reply) {
        showError('L’examinateur n’a pas répondu. Réessayez.');
        return;
      }

      history.push(
        { role: 'user', content: segment },
        { role: 'assistant', content: reply }
      );
      transcript.push({
        speaker: 'assistant',
        text: reply,
        timestamp: Date.now(),
      });

      pendingSegments.length = 0;
      examinerText = reply;
      examinerTextElement.textContent = reply;
    } catch (error) {
      console.error('[session] LLM request failed:', error);
      showError('L’examinateur n’a pas répondu. Réessayez.');
    } finally {
      isSending = false;
      updateButtons();
    }
  }

  async function handleSpeak() {
    const text = examinerText.trim();
    if (!text) {
      return;
    }
    clearError();
    await examinerAudio.play(text);
  }

  async function handleEndSession() {
    if (isEvaluating) {
      return;
    }
    if (!transcript.some((entry) => entry.speaker === 'user')) {
      showError('Répondez à au moins une question de l’examinateur avant de terminer la session.');
      return;
    }
    if (!window.confirm('Terminer la session et générer votre bilan ?')) {
      return;
    }

    isEvaluating = true;
    clearError();
    examinerAudio.stop();
    transcription.disconnect();
    audio.stop();
    updateButtons();

    try {
      const response = await fetch(configUrl('evaluateUrl'), {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'same-origin',
        body: JSON.stringify({ sessionId, transcript }),
      });

      if (response.status === 401) {
        window.location.href = configUrl('loginUrl');
        return;
      }

      const payload = await response.json().catch(() => ({}));

      if (!response.ok || !payload.data || !payload.data.feedbackUrl) {
        showError(payload.message || 'Le bilan n’a pas pu être généré.');
        isEvaluating = false;
        updateButtons();
        return;
      }

      window.location.href = payload.data.feedbackUrl;
    } catch (error) {
      console.error('[session] evaluation failed:', error);
      showError('Erreur réseau lors de la génération du bilan.');
      isEvaluating = false;
      updateButtons();
    }
  }

  connectButton.addEventListener('click', handleConnect);
  disconnectButton.addEventListener('click', handleDisconnect);
  sendButton.addEventListener('click', handleSend);
  speakButton.addEventListener('click', handleSpeak);
  endButton.addEventListener('click', handleEndSession);

  window.addEventListener('pagehide', () => {
    transcription.teardown();
    audio.teardown();
  });

  updateButtons();
  loadOpeningQuestion();
}
