// Apply the last selected theme before the first paint, including browser chrome.
(() => {
  const system = matchMedia('(prefers-color-scheme: dark)');
  let selected = 'system';
  function updateChrome() {
    const dark = selected === 'dark' || (selected === 'system' && system.matches);
    document.querySelectorAll('meta[name="theme-color"]').forEach(meta => {
      meta.content = selected === 'system'
        ? (meta.media.includes('dark') ? '#0f172a' : '#f6f8fb')
        : (dark ? '#0f172a' : '#f6f8fb');
    });
  }
  function apply(theme) {
    selected = ['light', 'dark', 'system'].includes(theme) ? theme : 'system';
    document.documentElement.dataset.theme = selected;
    try { localStorage.setItem('patchdeck-theme', selected); } catch { /* Storage is optional. */ }
    updateChrome();
  }
  let cached;
  try { cached = localStorage.getItem('patchdeck-theme'); } catch { /* Use the system theme. */ }
  apply(cached);
  system.addEventListener('change', updateChrome);
  window.PatchdeckTheme = {apply};
})();
