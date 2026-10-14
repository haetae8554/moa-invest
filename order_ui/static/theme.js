/* Apply before CSS is painted; theme preference stays on this browser. */
(() => {
  const media = matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = localStorage.getItem('moa-theme') || 'system'; } catch (_) {}
  if (!['system', 'light', 'dark'].includes(preference)) preference = 'system';
  const apply = () => {
    document.documentElement.dataset.theme = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
  };
  apply(); media.addEventListener('change', apply);
  window.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('theme'); select.value = preference;
    select.addEventListener('change', () => {
      preference = select.value;
      try { localStorage.setItem('moa-theme', preference); } catch (_) {}
      apply();
    });
  });
})();
