const element = document.getElementById('language-test-config');

let settings = {};
if (element) {
  try {
    settings = JSON.parse(element.textContent || '{}');
  } catch (error) {
    console.error('[language-test] invalid configuration:', error);
  }
}

export const languageTestConfig = settings;

export function configUrl(key) {
  return settings[key] || '';
}
