const pages = [...document.querySelectorAll('.page')];
const routes = [...document.querySelectorAll('[data-route]')];
const title = document.querySelector('#pageTitle');
const eyebrow = document.querySelector('#eyebrow');

function navigate(route) {
  const page = document.querySelector(`#${route}`) || document.querySelector('#overview');
  pages.forEach(candidate => candidate.classList.toggle('active', candidate === page));
  document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.route === page.id));
  title.textContent = page.dataset.title;
  eyebrow.textContent = page.dataset.eyebrow;
  history.replaceState(null, '', `#${page.id}`);
  document.querySelector('#commandPalette').close();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

routes.forEach(control => control.addEventListener('click', event => {
  event.preventDefault();
  navigate(control.dataset.route);
}));

const palette = document.querySelector('#commandPalette');
const commandInput = document.querySelector('#commandSearch');
function openPalette() {
  if (!palette.open) palette.showModal();
  commandInput.value = '';
  commandInput.focus();
  document.querySelectorAll('.palette-results button').forEach(item => { item.hidden = false; });
}
document.querySelector('#commandButton').addEventListener('click', openPalette);
document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    openPalette();
  }
  if (event.key === 'Escape' && palette.open) palette.close();
});
commandInput.addEventListener('input', () => {
  const query = commandInput.value.trim().toLowerCase();
  document.querySelectorAll('.palette-results button').forEach(item => {
    item.hidden = query && !item.textContent.toLowerCase().includes(query);
  });
});

const drawer = document.querySelector('#evidenceDrawer');
const scrim = document.querySelector('#scrim');
function setDrawer(open) {
  drawer.classList.toggle('open', open);
  scrim.classList.toggle('open', open);
  drawer.setAttribute('aria-hidden', String(!open));
}
document.querySelectorAll('.evidence-trigger').forEach(control => control.addEventListener('click', () => setDrawer(true)));
document.querySelector('#closeDrawer').addEventListener('click', () => setDrawer(false));
scrim.addEventListener('click', () => setDrawer(false));

const historySearch = document.querySelector('#historySearch');
const historyRows = [...document.querySelectorAll('.history-row')];
const historyEmpty = document.querySelector('#historyEmpty');
historySearch.addEventListener('input', () => {
  const query = historySearch.value.trim().toLowerCase();
  let visible = 0;
  historyRows.forEach(row => {
    const match = !query || `${row.textContent} ${row.dataset.keywords}`.toLowerCase().includes(query);
    row.hidden = !match;
    if (match) visible += 1;
  });
  historyEmpty.hidden = visible !== 0;
});
document.querySelector('#focusHistory').addEventListener('click', () => historySearch.focus());
historyRows.forEach(row => row.addEventListener('click', () => {
  historyRows.forEach(candidate => candidate.classList.toggle('active', candidate === row));
}));

document.querySelectorAll('.toggle').forEach(toggle => toggle.addEventListener('click', () => {
  const on = !toggle.classList.contains('on');
  toggle.classList.toggle('on', on);
  toggle.setAttribute('aria-pressed', String(on));
}));

navigate(location.hash.slice(1) || 'overview');
