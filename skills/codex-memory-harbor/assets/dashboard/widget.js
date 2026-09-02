const $ = selector => document.querySelector(selector);
let token = '';
let dockedCount = 0;
let accessibleCount = 0;

function showContinuity(volumeAvailable) {
  const healthy = accessibleCount === dockedCount && (dockedCount > 0 || volumeAvailable);
  $('#status').textContent = healthy ? '记忆都在' : '有些记忆暂时离线';
  $('#continuity-heading').textContent = healthy ? '随时可以回来' : '重新连接后可回来';
}

function showVolumes(volumes) {
  const volume = volumes.find(item => item.writable);
  showContinuity(Boolean(volume));
  $('#drive').textContent = volume ? `${volume.name} · ${volume.free_h} 可用` : '外置存储尚未连接';
}

async function repairLinks() {
  if (!token) return 0;
  const response = await fetch('/api/repair-links', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Harbor-Token': token},
    body: '{}',
  }).then(result => result.json());
  return response.repaired?.length || 0;
}

async function scan() {
  const data = await fetch('/api/scan?min_age=30').then(result => result.json());
  const docked = data.sessions.filter(item => item.linked);
  dockedCount = docked.length;
  accessibleCount = docked.filter(item => item.target_exists).length;
  $('#eligible').textContent = `${accessibleCount} / ${dockedCount}`;
  $('#continuity-note').textContent = data.totals.eligible_files
    ? `另有 ${data.totals.eligible_files} 项（${data.totals.eligible_h}）可安全停泊`
    : `${accessibleCount} 段历史已安全停泊`;
  showVolumes(data.volumes || []);
}

async function syncVolumes() {
  try {
    const data = await fetch('/api/volumes').then(result => result.json());
    showVolumes(data.volumes || []);
    if (await repairLinks()) await scan();
  } catch (error) {
    $('#status').textContent = '状态更新失败';
  }
}

async function load() {
  try {
    const config = await fetch('/api/config').then(result => result.json());
    token = config.token;
    await scan();
    if (await repairLinks()) await scan();
  } catch (error) {
    $('#status').textContent = '暂时看不清状态';
  }
}

window.harborVolumeChanged = syncVolumes;
$('#expand').onclick = () => { location.href = 'harbor://expand'; };
load();
