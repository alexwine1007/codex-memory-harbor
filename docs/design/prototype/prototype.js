const pages = [...document.querySelectorAll('.page')];
const pageButtons = [...document.querySelectorAll('[data-page]')];
const scrim = document.querySelector('#scrim');
const sheets = [...document.querySelectorAll('.sheet')];
const findDialog = document.querySelector('#findDialog');

const memories = {
  architecture: {
    kind: '产品决定',
    title: '让 Memory Harbor 成为所有 Agent 的共同港湾',
    summary: '核心保持运行时中立，Codex 只是第一个接入者；第二个真实接入将验证这条边界。',
    source: 'Codex · Memory Harbor',
    time: '今天 05:14',
  },
  method: {
    kind: '技术方法',
    title: '索引负责指路，原始历史负责举证',
    summary: '本地只保留少量、带出处、可撤销的线索。需要确认时，再按需读取外部原始记录。',
    source: 'Codex · 技术研究',
    time: '今天 04:38',
  },
  creative: {
    kind: '创作记录',
    title: '一次完整的影像项目证据审计',
    summary: '把生成、测试、交付和真正验收分开记录，让每个结论都能回到当时的依据。',
    source: 'Codex · 制作项目',
    time: '11 天前',
  },
};

function navigate(pageId) {
  const target = document.querySelector(`#${pageId}`) || document.querySelector('#harbor');
  pages.forEach(page => page.classList.toggle('active', page === target));
  document.querySelectorAll('nav [data-page]').forEach(button => button.classList.toggle('active', button.dataset.page === target.id));
  history.replaceState(null, '', `#${target.id}`);
  window.scrollTo({top: 0, behavior: 'smooth'});
}

pageButtons.forEach(button => button.addEventListener('click', () => navigate(button.dataset.page)));

function closeSheets() {
  sheets.forEach(sheet => {
    sheet.classList.remove('open');
    sheet.setAttribute('aria-hidden', 'true');
  });
  scrim.classList.remove('open');
}

function openSheet(name) {
  closeSheets();
  const sheet = document.querySelector(`#${name}Sheet`);
  if (!sheet) return;
  sheet.classList.add('open');
  sheet.setAttribute('aria-hidden', 'false');
  scrim.classList.add('open');
}

document.querySelectorAll('[data-sheet]').forEach(button => button.addEventListener('click', event => {
  event.stopPropagation();
  openSheet(button.dataset.sheet);
}));
document.querySelectorAll('.sheet-close').forEach(button => button.addEventListener('click', closeSheets));
scrim.addEventListener('click', closeSheets);

function showMemory(key) {
  const memory = memories[key] || memories.architecture;
  document.querySelector('#memoryKind').textContent = memory.kind;
  document.querySelector('#memoryTitle').textContent = memory.title;
  document.querySelector('#memorySummary').textContent = memory.summary;
  document.querySelector('#memorySource').textContent = memory.source;
  document.querySelector('#memoryTime').textContent = memory.time;
  openSheet('memory');
}

document.querySelectorAll('[data-memory]').forEach(button => button.addEventListener('click', () => showMemory(button.dataset.memory)));

function runRecall(query) {
  navigate('recall');
  const input = document.querySelector('#recallQuery');
  input.value = query;
  const normalized = query.trim().toLowerCase();
  let visible = 0;
  document.querySelectorAll('.result-card').forEach(card => {
    const terms = normalized.split(/\s+/).filter(Boolean);
    const haystack = `${card.textContent} ${card.dataset.keywords}`.toLowerCase();
    const match = !terms.length || terms.some(term => haystack.includes(term));
    card.hidden = !match;
    if (match) visible += 1;
  });
  document.querySelector('#noResult').hidden = visible !== 0;
}

document.querySelector('#heroRecall').addEventListener('submit', event => {
  event.preventDefault();
  runRecall(document.querySelector('#heroQuery').value);
});
document.querySelector('#recallForm').addEventListener('submit', event => {
  event.preventDefault();
  runRecall(document.querySelector('#recallQuery').value);
});
document.querySelectorAll('[data-query]').forEach(button => button.addEventListener('click', () => {
  findDialog.close();
  runRecall(button.dataset.query);
}));

function openFind() {
  if (!findDialog.open) findDialog.showModal();
  const input = document.querySelector('#dialogQuery');
  input.value = '';
  input.focus();
}

document.querySelector('#quickFind').addEventListener('click', openFind);
document.querySelector('#dialogSearch').addEventListener('submit', event => {
  event.preventDefault();
  const query = document.querySelector('#dialogQuery').value;
  findDialog.close();
  runRecall(query);
});
document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    openFind();
  }
  if (event.key === 'Escape') closeSheets();
});

const sea = document.querySelector('#memorySea');
document.addEventListener('pointermove', event => {
  const x = (event.clientX / window.innerWidth - .5) * 2;
  const y = (event.clientY / window.innerHeight - .5) * 2;
  sea.style.setProperty('--mx', x.toFixed(2));
  sea.style.setProperty('--my', y.toFixed(2));
});

const stars = document.querySelector('#stars');
for (let index = 0; index < 38; index += 1) {
  const star = document.createElement('i');
  star.className = 'star';
  star.style.left = `${(index * 47.3) % 100}%`;
  star.style.top = `${(index * 29.7 + 7) % 100}%`;
  star.style.setProperty('--opacity', String(.18 + (index % 5) * .09));
  star.style.setProperty('--duration', `${2.5 + (index % 7) * .5}s`);
  stars.appendChild(star);
}

navigate(location.hash.slice(1) || 'harbor');
