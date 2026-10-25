import { configUrl } from './config.js';
import { csrfHeaders } from './csrf.js';

const startButton = document.getElementById('start-session');
const errorElement = document.getElementById('setup-error');

if (startButton && errorElement) {
  const state = {
    language: null,
    examType: null,
    level: null,
    exerciseType: null,
  };

  let submitting = false;

  function showError(message) {
    errorElement.textContent = message;
    errorElement.classList.remove('hidden');
  }

  function clearError() {
    errorElement.textContent = '';
    errorElement.classList.add('hidden');
  }

  function updateButton() {
    startButton.disabled =
      submitting ||
      !state.language ||
      !state.examType ||
      !state.level ||
      !state.exerciseType;
    startButton.textContent = submitting ? 'Démarrage…' : 'Démarrer la session';
  }

  document.querySelectorAll('[data-group]').forEach((group) => {
    const key = group.dataset.group;
    const options = group.querySelectorAll('.option-card');

    options.forEach((option) => {
      option.addEventListener('click', () => {
        state[key] = option.dataset.value;
        options.forEach((item) => item.classList.toggle('is-selected', item === option));
        clearError();
        updateButton();
      });
    });
  });

  startButton.addEventListener('click', async () => {
    if (submitting) {
      return;
    }

    submitting = true;
    clearError();
    updateButton();

    try {
      const response = await fetch(configUrl('startUrl'), {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'same-origin',
        body: JSON.stringify(state),
      });

      if (response.status === 401) {
        window.location.href = configUrl('loginUrl');
        return;
      }

      const payload = await response.json().catch(() => ({}));

      if (!response.ok || !payload.data || !payload.data.sessionUrl) {
        showError(payload.message || 'Impossible de démarrer la session. Veuillez réessayer.');
        return;
      }

      window.location.href = payload.data.sessionUrl;
    } catch (error) {
      console.error('[setup] start session failed:', error);
      showError('Erreur réseau. Vérifiez votre connexion puis réessayez.');
    } finally {
      submitting = false;
      updateButton();
    }
  });

  updateButton();
}
