const api = (path, options = {}) => fetch(path, {
  ...options,
  headers: {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
    'X-Patchdeck-Request': '1'
  }
});
const text = value => String(value ?? '');
const esc = value => text(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let currentLanguage = 'en';
const I18N = {};

async function loadTranslations(language) {
  if (I18N[language]) return;
  const response = await fetch('/static/i18n/' + encodeURIComponent(language) + '.json');
  if (!response.ok) throw new Error('Translation file not found: ' + language);
  I18N[language] = await response.json();
}

async function selectLanguage(language) {
  await loadTranslations('en');
  if (language && language !== 'en') {
    try {
      await loadTranslations(language);
      currentLanguage = language;
      return;
    } catch {
      currentLanguage = 'en';
      return;
    }
  }
  currentLanguage = 'en';
}

function tr(key) {
  return (I18N[currentLanguage] && I18N[currentLanguage][key]) || (I18N.en && I18N.en[key]) || key;
}

function applyI18n() {
  document.documentElement.lang = currentLanguage;
  document.querySelectorAll('[data-i18n]').forEach(node => node.textContent = tr(node.dataset.i18n));
  document.querySelectorAll('[data-i18n-title]').forEach(node => node.title = tr(node.dataset.i18nTitle));
  document.querySelectorAll('[data-i18n-aria-label]').forEach(node => node.setAttribute('aria-label', tr(node.dataset.i18nAriaLabel)));
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme || 'system';
}

function refreshIcons() {
  document.querySelectorAll('i[data-lucide]').forEach(icon => {
    const name = icon.dataset.lucide;
    if (!name || !/^[a-z0-9-]+$/.test(name)) return;
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    const className = ['lucide', 'lucide-' + name, icon.getAttribute('class')].filter(Boolean).join(' ');
    svg.setAttribute('class', className);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('focusable', 'false');
    if (icon.getAttribute('aria-hidden')) svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(namespace, 'use');
    use.setAttribute('href', '/static/icons.svg#' + name);
    svg.appendChild(use);
    icon.replaceWith(svg);
  });
}

function serviceCountText(count) {
  return count + ' ' + (count === 1 ? tr('serviceSingular') : tr('servicePlural'));
}

async function getServices() {
  const services = await (await api('/api/services')).json();
  document.querySelector('#summary-services').textContent = serviceCountText(services.length);
  return services;
}

async function refreshAllServices() {
  const badge = document.querySelector('#refresh-status');
  if (badge) {
    badge.disabled = true;
    badge.classList.add('spin-icon');
    badge.innerHTML = '<i data-lucide="refresh-cw" aria-hidden="true"></i><span>' + esc(tr('refreshRunning')) + '</span>';
    refreshIcons();
  }
  try {
    const response = await api('/api/status?refresh=true');
    const statuses = await response.json();
    document.querySelector('#summary-services').textContent = serviceCountText(statuses.length);
    if (typeof renderServiceCards === 'function') {
      homeServiceOrder = statuses.map(service => service.service_id);
      updateAllButton(statuses);
      renderServiceCards(statuses);
      refreshIcons();
    }
  } finally {
    if (badge) {
      badge.disabled = false;
      badge.classList.remove('spin-icon');
      badge.innerHTML = '<i data-lucide="refresh-cw" aria-hidden="true"></i><span>' + esc(tr('refreshUpdates')) + '</span>';
      refreshIcons();
    }
  }
}

async function loadLanguagePreference(settings) {
  try {
    settings = settings || await (await api('/api/settings')).json();
    applyTheme(settings.theme);
    await selectLanguage(settings.language || 'en');
    applyI18n();
  } catch {
    await selectLanguage('en');
    applyI18n();
  }
}

function logoHtml(service) {
  if (service.logo_url) {
    return '<span class="logo service-icon"><img class="service-icon-image" src="' + esc(service.logo_url) + '" alt="" loading="lazy" referrerpolicy="no-referrer"></span>';
  }
  return '<div class="logo placeholder" aria-hidden="true"><i data-lucide="package"></i></div>';
}

function saveButton(action, labelKey = 'save') {
  const icon = labelKey === 'add' ? 'plus' : 'save';
  return '<button type="button" class="save-button" data-action="' + esc(action) + '"><i data-lucide="' + icon + '" aria-hidden="true"></i><span>' + esc(tr(labelKey)) + '</span></button>';
}

async function dispatchAction(target) {
  const serviceId = target.dataset.serviceId || '';
  switch (target.dataset.action) {
    case 'run-all-updates': await runAllUpdates(); break;
    case 'refresh-all-services': await refreshAllServices(); break;
    case 'run-update': await runUpdate(serviceId); break;
    case 'create-service': await createService(); break;
    case 'retry-save': retrySave(target.closest('.autosave-status')); break;
    case 'toggle-service-settings': toggleServiceSettings(serviceId); break;
    case 'delete-service': await deleteService(serviceId); break;
    case 'refresh-service': await refreshService(serviceId); break;
    case 'preview-release-notes': previewReleaseNotes(target.dataset.selector || ''); break;
    case 'scan-docker': await loadDockerCandidates(); break;
    case 'import-candidate': await importCandidate(serviceId); break;
    default: return;
  }
}

document.addEventListener('click', event => {
  const target = event.target instanceof Element ? event.target.closest('[data-action]') : null;
  if (!target || target.matches(':disabled')) return;
  dispatchAction(target).catch(error => console.error('Patchdeck action failed', error));
});
