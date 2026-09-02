let token='';
let data=null;
let filter='eligible';
let sortBy='size';
let frozenProjectOrder=null;
let config={protected_projects:[],protected_sessions:[]};
let activeTaskId='';
const selected=new Set();
const recommended=new Set();
const pinnedInView=new Set();
const expandedGroups=new Set();
const $=selector=>document.querySelector(selector);
const fmt=bytes=>{let value=bytes,units=['B','KB','MB','GB','TB'],index=0;while(value>=1024&&index<4){value/=1024;index++}return`${value.toFixed(value<10&&index?1:0)} ${units[index]}`};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

function toast(message,bad=false){const element=$('#toast');element.textContent=message;element.style.borderColor=bad?'#ff769455':'#48d7cb55';element.classList.add('show');setTimeout(()=>element.classList.remove('show'),3200)}
async function init(){const response=await fetch('/api/config').then(result=>result.json());token=response.token;config=response;bindStoragePicker();await refresh()}
async function refresh(resetOrder=true){if(resetOrder){frozenProjectOrder=null;pinnedInView.clear();expandedGroups.clear()}data=await fetch('/api/scan?'+new URLSearchParams({min_age:30})).then(result=>result.json());render()}
function isProtectedProject(path){return(config.protected_projects||[]).some(project=>path===project||path.startsWith(project+'/'))}
function groups(){
  const map=new Map();
  for(const item of data.sessions){
    const standalone=!item.project_id;
    const key=standalone?'__standalone__':item.project_id;
    const group=map.get(key)||{key,name:standalone?'未归类任务':item.project_name||'未命名项目',path:standalone?'':item.project_path||item.cwd,standalone,items:[],size:0,eligible:0,linked:0,recentDays:Infinity,protected:false};
    group.items.push(item);group.size+=item.logical;group.recentDays=Math.min(group.recentDays,item.age_days??Infinity);
    if(item.eligible)group.eligible+=item.logical;if(item.linked)group.linked+=item.logical;if(item.protected_project)group.protected=true;
    map.set(key,group);
  }
  const amount=group=>filter==='linked'?group.linked:filter==='recommended'?group.items.filter(item=>recommended.has(item.path)).reduce((sum,item)=>sum+item.logical,0):filter==='eligible'?group.eligible:group.size;
  const oldestVisible=group=>Math.max(-1,...visibleItems(group).map(item=>item.age_days));
  return[...map.values()].sort((a,b)=>sortBy==='recent'?oldestVisible(b)-oldestVisible(a)||amount(b)-amount(a):amount(b)-amount(a)||b.recentDays-a.recentDays);
}
function visibleItems(group){
  const items=group.items.filter(item=>filter==='all'||filter==='eligible'&&item.eligible||filter==='recommended'&&item.eligible&&recommended.has(item.path)||filter==='linked'&&item.linked);
  return items.sort((a,b)=>sortBy==='recent'?b.age_days-a.age_days||b.logical-a.logical:b.logical-a.logical||b.age_days-a.age_days);
}
function visible(group){return visibleItems(group).length>0||filter==='eligible'&&pinnedInView.has(group.key)}
function selectableItems(group){return group.items.filter(item=>filter==='linked'?item.linked:filter==='recommended'?item.eligible&&recommended.has(item.path):item.eligible)}
function groupPaths(group){return selectableItems(group).map(item=>item.path)}

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

function taskLabel(item){
  const shortId=item.id?item.id.slice(0,8):'无编号';
  if(!item.timestamp)return`${item.kind==='main'?'主任务':'子任务'} · ${shortId}`;
  const date=new Date(item.timestamp),valid=!Number.isNaN(date.getTime());
  return valid?`${item.kind==='main'?'主任务':'子任务'} · ${String(date.getMonth()+1).padStart(2,'0')}月${String(date.getDate()).padStart(2,'0')}日 ${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`:`${item.kind==='main'?'主任务':'子任务'} · ${shortId}`;
}
function taskTitle(item){return item.title||taskLabel(item)}
function taskState(item){
  if(item.protected_session)return['永久保留','protected'];
  if(item.protected_project)return['项目保留','protected'];
  if(item.linked&&!item.target_exists)return['目的地离线','offline'];
  if(item.linked)return['已停泊','linked'];
  if(item.kind==='main')return['主任务','protected'];
  if(!item.last_turn_complete)return['进行中','active'];
  if(item.eligible)return[filter==='recommended'?'本次推荐':'可整理','eligible'];
  return['近期任务','recent'];
}
function renderTask(item){
  const selectable=filter==='linked'?item.linked:item.eligible;
  const [state,stateClass]=taskState(item);
  const checked=selected.has(item.path);
  return`<div class="task-row ${checked?'selected':''}" data-task-row="${esc(item.path)}"><span class="branch-line"></span><input type="checkbox" data-task="${esc(item.path)}" ${checked?'checked':''} ${selectable?'':'disabled'}><span class="task-icon">${item.kind==='main'?'◆':'◇'}</span><button class="task-name task-title-button" data-detail-task="${esc(item.id||'')}"><b>${esc(taskTitle(item))}</b><span>${esc(taskLabel(item))} · ${esc(item.name)}</span></button><span class="task-size">${item.logical_h}</span><span class="task-age">${item.age_days} 天前</span><span class="task-state ${stateClass}">${state}</span>${item.id?`<button class="task-inspect" data-detail-task="${esc(item.id)}">查看</button><button class="pin task-pin ${item.protected_session?'on':''}" data-pin-session="${esc(item.id)}" title="${item.protected_session?'取消任务保留':'永久保留此任务'}">${item.protected_session?'★':'☆'}</button>`:'<span></span><span></span>'}</div>`;
}
function formatDate(value){if(!value)return'未知';const date=new Date(value);return Number.isNaN(date.getTime())?'未知':new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date)}
async function showTaskDetail(id){
  if(!id)return;
  try{
    const response=await post('/api/task-detail',{id});const task=response.task;activeTaskId=task.id;
    $('#taskDetailTitle').textContent=task.title||'未命名任务';
    $('#taskDetailPreview').textContent=task.preview||'这项任务没有可用的短预览，可以直接在 Codex 中打开查看。';
    $('#taskDetailMeta').innerHTML=`<div><span>最近更新</span><b>${esc(formatDate(task.updated_at_ms))}</b></div><div><span>${task.agent_nickname?'子代理':'创建时间'}</span><b>${esc(task.agent_nickname||formatDate(task.created_at_ms))}</b></div><div><span>工作目录</span><b>${esc(task.cwd||'未记录')}</b></div><div><span>任务编号</span><b>${esc(task.id)}</b></div>`;
    $('#taskDialog').showModal();
  }catch(error){toast(error.message,true)}
}
function renderProjects(){
  let projectGroups=groups().filter(visible);
  if(frozenProjectOrder){const rank=new Map(frozenProjectOrder.map((key,index)=>[key,index]));projectGroups.sort((a,b)=>(rank.get(a.key)??1e9)-(rank.get(b.key)??1e9))}
  $('#projects').innerHTML=projectGroups.length?projectGroups.map(group=>{
    const shown=visibleItems(group),paths=groupPaths(group),selectedPaths=paths.filter(path=>selected.has(path));
    const checked=paths.length>0&&selectedPaths.length===paths.length,partial=selectedPaths.length>0&&selectedPaths.length<paths.length;
    const amount=shown.reduce((sum,item)=>sum+item.logical,0),direct=!group.standalone&&isProtectedProject(group.path),protectedOn=direct||group.protected;
    const activity=sortBy==='recent'&&shown.length?`最久 ${shown[0].age_days} 天`:Number.isFinite(group.recentDays)?`最近 ${group.recentDays} 天`:'未知';
    const open=expandedGroups.has(group.key),recommendedGroup=shown.some(item=>recommended.has(item.path));
    const typeLabel=group.standalone?'独立任务':protectedOn?'长期保留':filter==='recommended'?`推荐 ${shown.length} 项`:filter==='linked'?'已停泊':'项目';
    return`<section class="tree-group ${group.standalone?'standalone':''} ${recommendedGroup?'recommended':''}"><div class="project"><button class="disclosure ${open?'open':''}" data-toggle-group="${esc(group.key)}" aria-label="${open?'收起':'展开'}">›</button><input type="checkbox" data-project="${esc(group.key)}" data-partial="${partial?'true':'false'}" ${checked?'checked':''} ${paths.length?'':'disabled'}><span class="project-icon">${group.standalone?'◇':'▱'}</span><button class="project-name project-toggle" data-toggle-group="${esc(group.key)}"><b>${esc(group.name)}</b><span>${esc(group.standalone?'未加入任何 Codex 项目的任务':group.path)}</span></button><span class="project-size">${fmt(amount)}</span><span class="project-count">${shown.length} 项 · ${activity}</span><span class="badge ${protectedOn?'bad':''}">${typeLabel}</span><span></span>${group.standalone?'<span></span>':`<button class="pin ${protectedOn?'on':''}" data-pin-project="${esc(group.path)}" title="${direct?'取消长期保留':protectedOn?'由同一真实路径保护':'长期保留项目'}" ${protectedOn&&!direct?'disabled':''}>${protectedOn?'★':'☆'}</button>`}</div>${open?`<div class="tree-children">${shown.map(renderTask).join('')}</div>`:''}</section>`;
  }).join(''):'<div class="empty">这里暂时没有符合当前条件的项目或任务</div>';
  document.querySelectorAll('[data-partial="true"]').forEach(control=>control.indeterminate=true);
  document.querySelectorAll('[data-toggle-group]').forEach(button=>button.onclick=()=>{const key=button.dataset.toggleGroup;expandedGroups.has(key)?expandedGroups.delete(key):expandedGroups.add(key);renderProjects()});
  document.querySelectorAll('[data-project]').forEach(control=>control.onchange=()=>{const group=groups().find(item=>item.key===control.dataset.project);for(const path of groupPaths(group))control.checked?selected.add(path):selected.delete(path);renderProjects();updateSelection()});
  document.querySelectorAll('[data-task]').forEach(control=>control.onchange=()=>{control.checked?selected.add(control.dataset.task):selected.delete(control.dataset.task);renderProjects();updateSelection()});
  document.querySelectorAll('[data-detail-task]').forEach(button=>button.onclick=()=>showTaskDetail(button.dataset.detailTask));
  document.querySelectorAll('[data-pin-project]').forEach(button=>button.onclick=async()=>{try{if(!frozenProjectOrder)frozenProjectOrder=groups().filter(visible).map(group=>group.key);const group=groups().find(candidate=>candidate.path===button.dataset.pinProject);if(group)pinnedInView.add(group.key);const enabled=!isProtectedProject(button.dataset.pinProject);const response=await post('/api/protect',{scope:'project',value:button.dataset.pinProject,enabled});config={...config,...response.settings};for(const item of group?.items||[])selected.delete(item.path);await refresh(false);toast(enabled?'项目已设为长期保留':'已取消项目保留')}catch(error){toast(error.message,true)}});
  document.querySelectorAll('[data-pin-session]').forEach(button=>button.onclick=async()=>{try{const enabled=!config.protected_sessions.includes(button.dataset.pinSession);const response=await post('/api/protect',{scope:'session',value:button.dataset.pinSession,enabled});config={...config,...response.settings};for(const item of data.sessions)if(item.id===button.dataset.pinSession)selected.delete(item.path);await refresh(false);toast(enabled?'任务已永久保留':'已取消任务保留')}catch(error){toast(error.message,true)}});
}
function updateSelection(){
  const items=data.sessions.filter(item=>selected.has(item.path)),projects=new Set(items.map(item=>item.project_id||'__standalone__')),linkedMode=filter==='linked';
  $('#selected').textContent=items.length?`已选 ${items.length} 个任务 · ${projects.size} 个分组`:'未选择任务';
  $('#selectedSize').textContent=fmt(items.reduce((total,item)=>total+(item.backup_exists?item.backup_bytes:item.logical),0));
  $('#offload').disabled=!items.length;$('#offload').textContent=items.length?(linkedMode?'管理所选':'整理所选'):(linkedMode?'选择已停泊任务':'选择任务后整理');
}
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
  selected.clear();recommended.clear();for(const item of recommendedItems()){selected.add(item.path);recommended.add(item.path)}
  expandedGroups.clear();for(const group of groups())if(group.items.some(item=>selected.has(item.path)))expandedGroups.add(group.key);
  filter='recommended';$('#recommendedTab').hidden=false;document.querySelectorAll('[data-filter]').forEach(button=>button.classList.toggle('active',button.dataset.filter==='recommended'));
  renderProjects();updateSelection();return data.sessions.filter(item=>selected.has(item.path));
}
async function prepareMigration(items,title='整理所选任务'){
  if(!$('#volume').value)throw Error('请先连接并选择一个可写外置盘');
  if(!items.length)throw Error('请先选择要整理的任务');
  const plan=await post('/api/plan',base(items.map(item=>item.path))),total=plan.results.reduce((sum,item)=>sum+item.bytes,0);
  if(!await ask(title,`<p>将安全整理 <b>${items.length}</b> 个已完成子任务，共 <b>${fmt(total)}</b>。</p><p>系统会逐条复制并校验；本地回滚不会自动删除。</p>`))return;
  await executeMigration(items);
}
function setProgress(completed,total,bytes,totalBytes,stage){$('#progressCount').textContent=`${completed} / ${total}`;$('#progressBytes').textContent=`${fmt(bytes)} / ${fmt(totalBytes)}`;$('#progressFill').style.width=(total?completed/total*100:0)+'%';$('#progressStage').textContent=stage}
async function executeMigration(items){
  const dialog=$('#progressDialog');$('#progressClose').disabled=true;$('#progressTitle').textContent='正在安全停泊';setProgress(0,items.length,0,items.reduce((sum,item)=>sum+item.logical,0),'逐条复制、校验并建立可读取连接…');dialog.showModal();
  let completed=0,bytes=0;
  try{
    for(const item of items){setProgress(completed,items.length,bytes,items.reduce((sum,current)=>sum+current.logical,0),`正在处理 ${item.name}`);await post('/api/offload',base([item.path]));completed++;bytes+=item.logical;setProgress(completed,items.length,bytes,items.reduce((sum,current)=>sum+current.logical,0),`已完成 ${completed} 项`)}
    $('#progressTitle').textContent='本轮整理完成';$('#progressStage').textContent='外置盘保持在线时，Codex 可沿原路径读取这些记录。';selected.clear();recommended.clear();await refresh();
  }catch(error){$('#progressTitle').textContent='整理已安全停止';$('#progressStage').textContent=error.message;toast(error.message,true)}
  $('#progressClose').disabled=false;
}

$('#compact').onclick=()=>location.href='harbor://compact';
$('#refresh').onclick=()=>refresh(true);
$('#sortBy').onchange=()=>{sortBy=$('#sortBy').value;frozenProjectOrder=null;pinnedInView.clear();renderProjects()};
document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(item=>item.classList.remove('active'));button.classList.add('active');filter=button.dataset.filter;frozenProjectOrder=null;pinnedInView.clear();if(filter!=='recommended'){selected.clear();recommended.clear();$('#recommendedTab').hidden=true}renderProjects();updateSelection()});
$('#selectAll').onclick=()=>{const items=selectRecommended();toast(items.length?`已推荐 ${items.length} 个安全候选，可逐项调整`:'暂时没有符合条件的候选')};
$('#optimize').onclick=async()=>{try{const items=selectRecommended();if(!items.length)throw Error('暂时没有符合 30 天安全条件的已完成子任务');await prepareMigration(items,'一键优化 · 本轮建议')}catch(error){toast(error.message,true)}};
$('#offload').onclick=async()=>{try{if(filter==='linked'){$('#manageDialog').showModal();return}await prepareMigration(data.sessions.filter(item=>selected.has(item.path)))}catch(error){toast(error.message,true)}};
$('#progressClose').onclick=()=>$('#progressDialog').close();
$('#openInCodex').onclick=()=>{if(activeTaskId)location.href=`codex://threads/${encodeURIComponent(activeTaskId)}`};
$('#audit').onclick=async()=>{try{const response=await post('/api/audit',{paths:[...selected]});toast(`已校验 ${response.results.length} 项，${response.results.filter(item=>item.verified).length} 项一致`)}catch(error){toast(error.message,true)}};
$('#restore').onclick=async()=>{try{$('#manageDialog').close();if(!await ask('恢复到内盘','<p>把所选停泊记录恢复为内盘普通文件，外挂副本仍保留。</p>'))return;await post('/api/restore',{paths:[...selected]});selected.clear();toast('已恢复');await refresh()}catch(error){toast(error.message,true)}};
$('#finalize').onclick=async()=>{try{$('#manageDialog').close();if(!await ask('释放本地回滚','<p>这一步会永久删除本地回滚副本，才真正腾出空间。外挂盘断开时，对应历史将暂时不可读。</p>'))return;await post('/api/finalize',{paths:[...selected],confirmation:'DELETE LOCAL BACKUPS'});selected.clear();toast('本地回滚已释放');await refresh()}catch(error){toast(error.message,true)}};

init().catch(error=>toast(error.message,true));
