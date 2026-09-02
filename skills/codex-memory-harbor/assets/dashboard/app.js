let token='';
let data=null;
let filter='eligible';
let sortBy='size';
let planned=false;
let frozenProjectOrder=null;
let config={protected_projects:[],protected_sessions:[]};
const selected=new Set();
const pinnedInView=new Set();
const $=selector=>document.querySelector(selector);
const fmt=bytes=>{let value=bytes,units=['B','KB','MB','GB','TB'],index=0;while(value>=1024&&index<4){value/=1024;index++}return`${value.toFixed(value<10&&index?1:0)} ${units[index]}`};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

function toast(message,bad=false){const element=$('#toast');element.textContent=message;element.style.borderColor=bad?'#ff769455':'#48d7cb55';element.classList.add('show');setTimeout(()=>element.classList.remove('show'),3200)}
async function init(){const response=await fetch('/api/config').then(result=>result.json());token=response.token;config=response;bindStoragePicker();await refresh()}
async function refresh(resetOrder=true){if(resetOrder){frozenProjectOrder=null;pinnedInView.clear()}planned=false;$('#offload').disabled=true;data=await fetch('/api/scan?'+new URLSearchParams({min_age:30})).then(result=>result.json());render()}
function isProtectedProject(path){return(config.protected_projects||[]).some(project=>path===project||path.startsWith(project+'/'))}
function groups(){
  const map=new Map();
  for(const item of data.sessions){
    const key=item.cwd||'未知项目';
    const group=map.get(key)||{key,name:key.split('/').filter(Boolean).pop()||'未知项目',items:[],size:0,eligible:0,linked:0,recentDays:Infinity,protected:false};
    group.items.push(item);group.size+=item.logical;group.recentDays=Math.min(group.recentDays,item.age_days??Infinity);
    if(item.eligible)group.eligible+=item.logical;if(item.linked)group.linked+=item.logical;if(item.protected_project)group.protected=true;
    map.set(key,group);
  }
  const amount=group=>filter==='linked'?group.linked:filter==='eligible'?group.eligible:group.size;
  return[...map.values()].sort((a,b)=>sortBy==='recent'?a.recentDays-b.recentDays||amount(b)-amount(a):amount(b)-amount(a)||a.recentDays-b.recentDays);
}
function visible(group){return filter==='all'||filter==='eligible'&&(group.items.some(item=>item.eligible)||pinnedInView.has(group.key))||filter==='linked'&&group.items.some(item=>item.linked)}
function groupPaths(group){return group.items.filter(item=>filter==='linked'?item.linked:item.eligible).map(item=>item.path)}

function storageTargets(volumes){
  return [
    ...(volumes||[]).filter(volume=>volume.writable).map(volume=>({id:`external:${volume.path}`,kind:'external_volume',location:volume.path,name:volume.name,detail:`${volume.free_h} 可用`,available:true})),
    {id:'cloud:future',kind:'cloud',location:'',name:'Memory Harbor Cloud',detail:'未来可接入私有云、S3 或 OSS',available:false}
  ];
}
function renderStorageTargets(volumes){
  const targets=storageTargets(volumes);
  const currentPath=$('#volume').value;
  const available=targets.filter(target=>target.available);
  const current=available.find(target=>target.location===currentPath)||available[0];
  $('#volume').value=current?.location||'';
  $('#driveStatus').textContent=current?'存储目的地 · 外置盘在线':'存储目的地 · 等待连接';
  $('#driveName').textContent=current?`${current.name} · ${current.detail}`:'连接外置硬盘后可整理';
  $('#driveMenu').innerHTML=targets.map(target=>target.available
    ?`<button class="drive-option ${target.location===$('#volume').value?'active':''}" type="button" role="option" data-volume="${esc(target.location)}"><b>${esc(target.name)}</b><span>外置存储 · ${esc(target.detail)}</span><em>${target.location===$('#volume').value?'✓':''}</em></button>`
    :`<div class="drive-option future" role="option" aria-disabled="true"><b>${esc(target.name)}</b><span>${esc(target.detail)}</span><em>即将支持</em></div>`).join('');
  document.querySelectorAll('[data-volume]').forEach(button=>button.onclick=()=>{selectStorage(button.dataset.volume);closeStorageMenu()});
}
function selectStorage(path){$('#volume').value=path;renderStorageTargets(data.volumes||[])}
function closeStorageMenu(){const menu=$('#driveMenu');menu.hidden=true;$('#drivePicker').setAttribute('aria-expanded','false')}
function bindStoragePicker(){
  $('#drivePicker').onclick=event=>{event.stopPropagation();const opening=$('#driveMenu').hidden;$('#driveMenu').hidden=!opening;$('#drivePicker').setAttribute('aria-expanded',String(opening))};
  document.addEventListener('click',event=>{if(!event.target.closest('.drive-control'))closeStorageMenu()});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeStorageMenu()});
}
function render(){
  const totals=data.totals;
  $('#eligible').textContent=totals.eligible_h;
  $('#heroText').textContent=`${totals.eligible_files} 个静置子任务符合安全条件；迁移后先保留回滚，不会立即删除。`;
  $('#free').textContent=data.disk.free_h;$('#diskBar').style.width=data.disk.used_percent+'%';
  $('#protected').textContent=totals.main_files+' 个';$('#linked').textContent=totals.linked_files+' 个';$('#rollback').textContent=totals.rollback_h;
  renderStorageTargets(data.volumes||[]);renderProjects();updateSelection();
}
async function syncVolumes(){try{const response=await fetch('/api/volumes').then(result=>result.json());data.volumes=response.volumes||[];renderStorageTargets(data.volumes)}catch(error){$('#driveStatus').textContent='存储目的地 · 状态未知'}}
window.harborVolumeChanged=syncVolumes;

function renderProjects(){
  let projectGroups=groups().filter(visible);
  if(frozenProjectOrder){const rank=new Map(frozenProjectOrder.map((key,index)=>[key,index]));projectGroups.sort((a,b)=>(rank.get(a.key)??1e9)-(rank.get(b.key)??1e9))}
  $('#projects').innerHTML=projectGroups.length?projectGroups.map(group=>{
    const paths=groupPaths(group),checked=paths.length&&paths.every(path=>selected.has(path));
    const amount=filter==='linked'?group.linked:filter==='eligible'?group.eligible:group.size;
    const direct=isProtectedProject(group.key),protectedOn=direct||group.protected;
    const label=protectedOn?'长期保留':filter==='linked'?'已停泊':filter==='eligible'?'可整理':'项目';
    const activity=Number.isFinite(group.recentDays)?`${group.recentDays} 天前`:'未知';
    return`<div class="project"><input type="checkbox" data-project="${esc(group.key)}" ${checked?'checked':''} ${paths.length?'':'disabled'}><div class="project-name"><b>${esc(group.name)}</b><span>${esc(group.key)}</span></div><span class="project-size">${fmt(amount)}</span><span class="project-count">${paths.length} 个 · ${activity}</span><span class="badge ${protectedOn?'bad':''}">${label}</span><button class="pin ${protectedOn?'on':''}" data-pin-project="${esc(group.key)}" title="${direct?'取消长期保留':protectedOn?'由同一真实路径保护':'长期保留项目'}" ${protectedOn&&!direct?'disabled':''}>${protectedOn?'★':'☆'}</button></div>`;
  }).join(''):'<div class="empty">这里暂时没有项目</div>';
  document.querySelectorAll('[data-project]').forEach(control=>control.onchange=()=>{const group=groups().find(item=>item.key===control.dataset.project);for(const path of groupPaths(group))control.checked?selected.add(path):selected.delete(path);planned=false;$('#offload').disabled=true;renderProjects();updateSelection()});
  document.querySelectorAll('[data-pin-project]').forEach(button=>button.onclick=async()=>{try{if(!frozenProjectOrder)frozenProjectOrder=groups().filter(visible).map(group=>group.key);pinnedInView.add(button.dataset.pinProject);const enabled=!isProtectedProject(button.dataset.pinProject);const response=await post('/api/protect',{scope:'project',value:button.dataset.pinProject,enabled});config={...config,...response.settings};for(const item of data.sessions)if(item.cwd===button.dataset.pinProject)selected.delete(item.path);await refresh(false);toast(enabled?'项目已设为长期保留':'已取消项目保留')}catch(error){toast(error.message,true)}});
}
function renderFiles(){
  const picked=data.sessions.filter(item=>selected.has(item.path));
  const kept=data.sessions.filter(item=>item.protected_session&&!selected.has(item.path));
  const items=[...picked,...kept];
  $('#files').innerHTML=items.length?items.map(item=>`<div class="file"><span>${esc(item.path)}</span><span>${item.logical_h}</span><span>${item.age_days} 天</span><span>${item.protected_session?'永久保留':item.linked?'已停泊':'可迁移'}</span>${item.id?`<button class="pin ${item.protected_session?'on':''}" data-pin-session="${esc(item.id)}">${item.protected_session?'取消保留':'永久保留'}</button>`:'<span></span>'}</div>`).join(''):'<div class="empty">选择项目后可查看文件，并单独标记重要任务</div>';
  document.querySelectorAll('[data-pin-session]').forEach(button=>button.onclick=async()=>{try{const enabled=!config.protected_sessions.includes(button.dataset.pinSession);const response=await post('/api/protect',{scope:'session',value:button.dataset.pinSession,enabled});config={...config,...response.settings};for(const item of data.sessions)if(item.id===button.dataset.pinSession)selected.delete(item.path);await refresh();toast(enabled?'任务已永久保留':'已取消任务保留')}catch(error){toast(error.message,true)}});
}
function updateSelection(){const items=data.sessions.filter(item=>selected.has(item.path));$('#selected').textContent=items.length?`已选 ${new Set(items.map(item=>item.cwd)).size} 个项目`:'未选择项目';$('#selectedSize').textContent=fmt(items.reduce((total,item)=>total+(item.backup_exists?item.backup_bytes:item.logical),0));renderFiles()}
async function post(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Harbor-Token':token},body:JSON.stringify(body)});const json=await response.json();if(!response.ok||!json.ok)throw Error(json.error||'操作失败');return json}
function base(paths=[...selected]){return{paths,volume:$('#volume').value,storage_target:{provider:'external_volume',location:$('#volume').value},min_age:30,priority:(config.protected_projects||[]).join('\n'),archive_name:'Codex Memory Harbor'}}
async function ask(title,html){$('#dialogTitle').textContent=title;$('#dialogBody').innerHTML=html;const dialog=$('#dialog');dialog.showModal();return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='ok'),{once:true}))}

function recommendedItems(){
  const maximumFiles=25,maximumBytes=5*1024**3;
  const candidates=data.sessions.filter(item=>item.eligible).sort((a,b)=>((b.logical*Math.log2(2+b.age_days))-(a.logical*Math.log2(2+a.age_days))));
  const result=[];let total=0;
  for(const item of candidates){if(result.length>=maximumFiles)break;if(result.length&&total+item.logical>maximumBytes)continue;result.push(item);total+=item.logical}
  return result;
}
function selectRecommended(){
  selected.clear();for(const item of recommendedItems())selected.add(item.path);
  filter='eligible';document.querySelectorAll('[data-filter]').forEach(button=>button.classList.toggle('active',button.dataset.filter==='eligible'));
  renderProjects();updateSelection();return data.sessions.filter(item=>selected.has(item.path));
}
function setProgress(completed,total,bytes,totalBytes,stage){$('#progressCount').textContent=`${completed} / ${total}`;$('#progressBytes').textContent=`${fmt(bytes)} / ${fmt(totalBytes)}`;$('#progressFill').style.width=(total?completed/total*100:0)+'%';$('#progressStage').textContent=stage}
async function executeMigration(items){
  const dialog=$('#progressDialog');$('#progressClose').disabled=true;$('#progressTitle').textContent='正在安全停泊';setProgress(0,items.length,0,items.reduce((sum,item)=>sum+item.logical,0),'逐条复制、校验并建立可读取连接…');dialog.showModal();
  let completed=0,bytes=0;
  try{
    for(const item of items){setProgress(completed,items.length,bytes,items.reduce((sum,current)=>sum+current.logical,0),`正在处理 ${item.name}`);await post('/api/offload',base([item.path]));completed++;bytes+=item.logical;setProgress(completed,items.length,bytes,items.reduce((sum,current)=>sum+current.logical,0),`已完成 ${completed} 项`)}
    $('#progressTitle').textContent='本轮整理完成';$('#progressStage').textContent='外置盘保持在线时，Codex 可沿原路径读取这些记录。';selected.clear();await refresh();
  }catch(error){$('#progressTitle').textContent='整理已安全停止';$('#progressStage').textContent=error.message;toast(error.message,true)}
  $('#progressClose').disabled=false;
}

$('#compact').onclick=()=>location.href='harbor://compact';
$('#refresh').onclick=()=>refresh(true);
$('#sortBy').onchange=()=>{sortBy=$('#sortBy').value;frozenProjectOrder=null;pinnedInView.clear();renderProjects()};
document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(item=>item.classList.remove('active'));button.classList.add('active');filter=button.dataset.filter;frozenProjectOrder=null;pinnedInView.clear();selected.clear();planned=false;$('#offload').disabled=true;renderProjects();updateSelection()});
$('#selectAll').onclick=()=>{const items=selectRecommended();toast(items.length?`已推荐 ${items.length} 个安全候选，可逐项调整`:'暂时没有符合条件的候选')};
$('#optimize').onclick=async()=>{try{if(!$('#volume').value)throw Error('请先连接并选择一个可写外置盘');const items=selectRecommended();if(!items.length)throw Error('暂时没有符合 30 天安全条件的已完成子任务');const plan=await post('/api/plan',base(items.map(item=>item.path)));const total=plan.results.reduce((sum,item)=>sum+item.bytes,0);if(!await ask('一键优化 · 本轮安全批次',`<p>推荐 <b>${items.length}</b> 个已完成子任务，共 <b>${fmt(total)}</b>。为便于验证，当前测试版每轮最多 25 项 / 5 GB。</p><p>将逐条复制、哈希校验并建立透明链接；本地回滚不会自动删除。</p>`))return;await executeMigration(items)}catch(error){toast(error.message,true)}};
$('#plan').onclick=async()=>{try{const response=await post('/api/plan',base());const total=response.results.reduce((sum,item)=>sum+item.bytes,0);if(await ask('整理方案预演',`<p>共 <b>${response.results.length}</b> 个子任务、<b>${fmt(total)}</b>。将先复制和哈希校验，内盘回滚仍保留。</p><div class="plan-list">${response.results.map(item=>`<div>${esc(item.source)}<br>→ ${esc(item.destination)}</div>`).join('')}</div>`)){planned=true;$('#offload').disabled=false;toast('预演通过，已解锁迁移')}}catch(error){toast(error.message,true)}};
$('#offload').onclick=async()=>{if(!planned)return;try{const items=data.sessions.filter(item=>selected.has(item.path));if(!await ask('开始安全迁移','<p>按项目逐条复制、校验并链接；首个失败会停止。不会删除本地回滚。</p>'))return;await executeMigration(items)}catch(error){toast(error.message,true)}};
$('#progressClose').onclick=()=>$('#progressDialog').close();
$('#audit').onclick=async()=>{try{const response=await post('/api/audit',{paths:[...selected]});toast(`已校验 ${response.results.length} 项，${response.results.filter(item=>item.verified).length} 项一致`)}catch(error){toast(error.message,true)}};
$('#restore').onclick=async()=>{try{if(!await ask('恢复到内盘','<p>把所选停泊记录恢复为内盘普通文件，外挂副本仍保留。</p>'))return;await post('/api/restore',{paths:[...selected]});selected.clear();toast('已恢复');await refresh()}catch(error){toast(error.message,true)}};
$('#finalize').onclick=async()=>{try{if(!await ask('释放本地回滚','<p>这一步会永久删除本地回滚副本，才真正腾出空间。外挂盘断开时，对应历史将暂时不可读。</p>'))return;await post('/api/finalize',{paths:[...selected],confirmation:'DELETE LOCAL BACKUPS'});selected.clear();toast('本地回滚已释放');await refresh()}catch(error){toast(error.message,true)}};

init().catch(error=>toast(error.message,true));
