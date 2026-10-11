let token='';
let data=null;
let filter='eligible';
let sortBy='size';
let frozenProjectOrder=null;
let config={protected_projects:[],protected_sessions:[]};
let activeTaskId='';
let activeTask=null;
let searchMatches=null;
let searchResults=[];
let searchTimer=0;
let operationBusy=false;
let projectFilePlan=null;
let projectFilePage=0;
const selectedProjectFiles=new Set();
const selectedParkedProjectFiles=new Set();
const selected=new Set();
const recommended=new Set();
const pinnedInView=new Set();
const expandedGroups=new Set();
const $=selector=>document.querySelector(selector);
const fmt=bytes=>{let value=bytes,units=['B','KB','MB','GB','TB'],index=0;while(value>=1024&&index<4){value/=1024;index++}return`${value.toFixed(value<10&&index?1:0)} ${units[index]}`};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

function toast(message,bad=false){const element=$('#toast');element.textContent=message;element.style.borderColor=bad?'#ff769455':'#48d7cb55';element.classList.add('show');setTimeout(()=>element.classList.remove('show'),3200)}
async function init(){const response=await fetch('/api/config').then(result=>result.json());token=response.token;config=response;bindStoragePicker();installProjectStorage();await refresh()}
async function refresh(resetOrder=true){if(resetOrder){frozenProjectOrder=null;pinnedInView.clear();expandedGroups.clear()}data=await fetch('/api/scan?'+new URLSearchParams({min_age:30})).then(result=>result.json());render()}
function isProtectedProject(path){return(config.protected_projects||[]).some(project=>path===project||path.startsWith(project+'/'))}
function indexedItems(){
  if(!searchMatches)return data.sessions;
  const matches=new Map(searchResults.map(item=>[item.source_path,item]));
  const local=data.sessions.map(item=>matches.has(item.path)?{...item,match_excerpt:matches.get(item.path).match_excerpt,match_role:matches.get(item.path).match_role,match_source_line:matches.get(item.path).match_source_line}:item);
  const known=new Set(data.sessions.map(item=>item.path));
  const indexed=searchResults.filter(item=>!known.has(item.source_path)).map(item=>{
    const timestamp=item.timestamp?new Date(item.timestamp):null;
    const age=timestamp&&!Number.isNaN(timestamp.getTime())?Math.max(0,Math.round((Date.now()-timestamp.getTime())/8640000)/10):null;
    return{path:item.source_path,name:item.source_path.split('/').pop()||'索引记录',id:item.thread_id,parent_id:item.parent_id,title:item.title,project_id:item.project_id,project_name:item.project_name,project_path:item.project_path,cwd:item.cwd,agent_path:item.agent_path,timestamp:item.timestamp,kind:item.kind||'child',logical:Number(item.logical)||0,logical_h:fmt(Number(item.logical)||0),age_days:age,linked:Boolean(item.linked),target:item.target_path,target_exists:Boolean(item.target_available),source_present:Boolean(item.source_present),catalog_only:true,eligible:false,last_turn_complete:true,protected_session:false,protected_project:false,match_excerpt:item.match_excerpt,match_role:item.match_role,match_source_line:item.match_source_line};
  });
  return[...local,...indexed];
}
function groups(){
  const map=new Map();
  for(const item of indexedItems()){
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
  const items=group.items.filter(item=>searchMatches?searchMatches.has(item.path):filter==='all'||filter==='eligible'&&item.eligible||filter==='recommended'&&item.eligible&&recommended.has(item.path)||filter==='linked'&&item.linked);
  const age=item=>item.age_days??-1;
  return items.sort((a,b)=>sortBy==='recent'?age(b)-age(a)||b.logical-a.logical:b.logical-a.logical||age(b)-age(a));
}
function visible(group){return visibleItems(group).length>0||filter==='eligible'&&pinnedInView.has(group.key)}
function selectableItems(group){return group.items.filter(item=>!item.catalog_only&&(filter==='linked'?item.linked:filter==='recommended'?item.eligible&&recommended.has(item.path):item.eligible))}
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
  $('#heroText').textContent=(totals.eligible_files?`${totals.eligible_files} 段已经完成的历史符合安全条件。`:'今天没有新增可停泊历史。')+'这里不含已停泊历史，也不含项目视频、图片等大素材；素材请查看项目存储方案。';
  $('#free').textContent=data.disk.free_h;$('#diskBar').style.width=data.disk.used_percent+'%';
  $('#protected').textContent=totals.main_files+' 个';$('#linked').textContent=totals.linked_files+' 个';$('#rollback').textContent=totals.rollback_h;
  const recalled=data.catalog?.recall_sessions||0;
  $('#catalogStatus').textContent=`本地索引 ${data.catalog?.items??totals.files} 项${recalled?` · ${recalled} 项可内容召回`:''}`;
  renderStorageTargets(data.volumes||[]);renderProjects();updateSelection();
}

async function runSearch(){
  const query=$('#search').value.trim();
  $('#clearSearch').hidden=!query;
  if(!query){searchMatches=null;searchResults=[];renderProjects();return}
  try{
    const response=await fetch('/api/recall?'+new URLSearchParams({q:query,limit:100})).then(result=>result.json());
    searchResults=response.results||[];
    searchMatches=new Set(searchResults.map(item=>item.source_path));
    expandedGroups.clear();for(const group of groups())if(group.items.some(item=>searchMatches.has(item.path)))expandedGroups.add(group.key);
    renderProjects();
  }catch(error){toast('搜索索引暂不可用',true)}
}
async function syncVolumes(){
  try{
    const response=await fetch('/api/volumes').then(result=>result.json());data.volumes=response.volumes||[];renderStorageTargets(data.volumes);
    const repair=await post('/api/repair-links',{});
    if(repair.repaired?.length){toast(`已安全恢复 ${repair.repaired.length} 条存储连接`);await refresh(false)}
  }catch(error){$('#driveStatus').textContent='存储目的地 · 状态未知'}
}
window.harborVolumeChanged=syncVolumes;

function taskLabel(item){
  const shortId=item.id?item.id.slice(0,8):'无编号';
  if(!item.timestamp)return`${item.kind==='main'?'主任务':'子任务'} · ${shortId}`;
  const date=new Date(item.timestamp),valid=!Number.isNaN(date.getTime());
  return valid?`${item.kind==='main'?'主任务':'子任务'} · ${String(date.getMonth()+1).padStart(2,'0')}月${String(date.getDate()).padStart(2,'0')}日 ${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`:`${item.kind==='main'?'主任务':'子任务'} · ${shortId}`;
}
function taskTitle(item){return item.title||taskLabel(item)}
function taskState(item){
  if(item.catalog_only&&!item.target_exists)return['仅索引可见','offline'];
  if(item.catalog_only)return['停泊原件','linked'];
  if(item.protected_session)return['永久保留','protected'];
  if(item.protected_project)return['项目保留','protected'];
  if(item.linked&&!item.target_exists)return['存储未连接','offline'];
  if(item.linked)return['已停泊','linked'];
  if(item.kind==='main')return['主任务','protected'];
  if(!item.last_turn_complete)return['进行中','active'];
  if(item.eligible)return[filter==='recommended'?'本次推荐':'可停泊','eligible'];
  return['近期任务','recent'];
}
function renderTask(item){
  const selectable=!item.catalog_only&&(filter==='linked'?item.linked:item.eligible);
  const [state,stateClass]=taskState(item);
  const checked=selected.has(item.path);
  const age=item.age_days==null?'时间未知':`${item.age_days} 天前`;
  const secondary=item.match_excerpt?`命中${item.match_role==='instruction'?'任务指令':'任务结论'} · ${item.match_excerpt}`:`${taskLabel(item)} · ${item.name}`;
  return`<div class="task-row ${checked?'selected':''}" data-task-row="${esc(item.path)}"><span class="branch-line"></span><input type="checkbox" data-task="${esc(item.path)}" ${checked?'checked':''} ${selectable?'':'disabled'}><span class="task-icon">${item.kind==='main'?'◆':'◇'}</span><button class="task-name task-title-button" data-detail-task="${esc(item.id||'')}"><b>${esc(taskTitle(item))}</b><span class="${item.match_excerpt?'match-excerpt':''}">${esc(secondary)}</span></button><span class="task-size">${item.logical_h}</span><span class="task-age">${age}</span><span class="task-state ${stateClass}">${state}</span>${item.id?`<button class="task-inspect" data-detail-task="${esc(item.id)}">查看</button><button class="pin task-pin ${item.protected_session?'on':''}" data-pin-session="${esc(item.id)}" title="${item.protected_session?'取消任务保留':'永久保留此任务'}">${item.protected_session?'★':'☆'}</button>`:'<span></span><span></span>'}</div>`;
}
function formatDate(value){if(!value)return'未知';const date=new Date(value);return Number.isNaN(date.getTime())?'未知':new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date)}
async function showTaskDetail(id){
  if(!id)return;
  try{
    const response=await post('/api/task-detail',{id});const task=response.task;activeTask=task;activeTaskId=task.id;
    $('#taskDetailTitle').textContent=task.title||'未命名任务';
    $('#taskDetailPreview').textContent=task.preview||(task.is_subagent?'这是从所属主任务拆出的后台协作任务，可在下方按需查看它的工作汇报。':'这项任务没有可用的短预览，可以直接在 Codex 中打开查看。');
    $('#taskDetailMeta').innerHTML=`<div><span>最近更新</span><b>${esc(formatDate(task.updated_at_ms))}</b></div><div><span>${task.agent_nickname?'子代理':'创建时间'}</span><b>${esc(task.agent_nickname||formatDate(task.created_at_ms))}</b></div><div><span>工作目录</span><b>${esc(task.cwd||'未记录')}</b></div><div><span>任务编号</span><b>${esc(task.id)}</b></div>`;
    $('#taskRecord').hidden=true;$('#taskRecordMessages').innerHTML='';$('#taskRecordCount').textContent='';
    $('#openParentInCodex').hidden=!task.is_subagent;
    $('#openInCodex').textContent=task.is_subagent?'查看任务记录':'在 Codex 中打开';
    $('#taskDetailHint').textContent=task.is_subagent?'旧版多代理子任务无法被 Codex 单独恢复；记忆港可按需读取子代理对外汇报，不展开工具原始输出。':'这里只读取 Codex 已生成的标题和短预览，不扫描完整对话正文。';
    $('#taskDialog').showModal();
  }catch(error){toast(error.message,true)}
}
function renderProjects(){
  renderProjectStorage();
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
  $('#selected').textContent=items.length?`已选 ${items.length} 个历史对象 · ${projects.size} 个分组`:'未选择历史';
  $('#selectedSize').textContent=fmt(items.reduce((total,item)=>total+(item.backup_exists?item.backup_bytes:item.logical),0));
  $('#offload').disabled=operationBusy||!items.length;$('#offload').textContent=operationBusy?'操作进行中…':items.length?(linkedMode?'管理所选':'停泊所选'):(linkedMode?'选择已停泊历史':'选择历史后停泊');
  $('#optimize').disabled=operationBusy;$('#selectAll').disabled=operationBusy;
}
async function post(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Harbor-Token':token},body:JSON.stringify(body)});const json=await response.json();if(!response.ok||!json.ok)throw Error(json.error||'操作失败');return json}
function base(paths=[...selected]){return{paths,volume:$('#volume').value,storage_target:{provider:'external_volume',location:$('#volume').value},min_age:30,priority:(config.protected_projects||[]).join('\n'),archive_name:'Memory Harbor'}}
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
async function prepareMigration(items,title='停泊所选历史'){
  if(operationBusy){toast('已有停泊操作正在进行');return}
  operationBusy=true;updateSelection();
  try{
    if(!$('#volume').value)throw Error('请先连接并选择一个可写外置盘');
    if(!items.length)throw Error('请先选择要停泊的历史');
    const plan=await post('/api/plan',base(items.map(item=>item.path))),total=plan.results.reduce((sum,item)=>sum+item.bytes,0);
    const confirmed=await ask(title,`<p>将停泊 <b>${items.length}</b> 个已完成历史对象，共 <b>${fmt(total)}</b>。</p><p>每项都会先复制、校验并建立可读取连接；独立复核通过后才释放本地实体。</p><label class="backup-option"><input id="keepLocalBackup" type="checkbox"><span><b>同时保留本地副本</b><small>用于额外观察；不会释放这部分内盘空间</small></span></label>`);
    const keepLocalBackup=Boolean($('#keepLocalBackup')?.checked);
    if(!confirmed)return;
    await executeMigration(items,{keepLocalBackup});
  }finally{operationBusy=false;updateSelection()}
}
function setProgress(completed,total,bytes,totalBytes,stage){$('#progressCount').textContent=`${completed} / ${total}`;$('#progressBytes').textContent=`${fmt(bytes)} / ${fmt(totalBytes)}`;$('#progressFill').style.width=(total?completed/total*100:0)+'%';$('#progressStage').textContent=stage}
async function executeMigration(items,{keepLocalBackup=false}={}){
  const dialog=$('#progressDialog'),totalBytes=items.reduce((sum,item)=>sum+item.logical,0);$('#progressClose').disabled=true;$('#progressTitle').textContent=keepLocalBackup?'正在停泊并保留副本':'正在安全停泊';setProgress(0,items.length,0,totalBytes,'逐条复制、验证并建立连续性连接…');dialog.showModal();
  let completed=0,bytes=0,released=0;
  try{
    for(const item of items){
      setProgress(completed,items.length,bytes,totalBytes,`正在处理 ${item.name}`);
      const response=await post(keepLocalBackup?'/api/offload':'/api/migrate',base([item.path]));
      released+=Number(response.results?.[0]?.bytes_released||0);completed++;bytes+=item.logical;
      setProgress(completed,items.length,bytes,totalBytes,keepLocalBackup?`已停泊并保留 ${completed} 项`:`已停泊并释放 ${completed} 项`);
    }
    $('#progressTitle').textContent=keepLocalBackup?'本轮停泊完成':'本轮安全停泊完成';
    $('#progressStage').textContent=keepLocalBackup?'已保留本地副本；外置盘原件和原路径连接均已验证。':`已释放 ${fmt(released)} 内盘空间；外置盘在线时 Codex 可沿原路径读取。`;
    selected.clear();recommended.clear();await refresh();
  }catch(error){$('#progressTitle').textContent='操作已安全停止';$('#progressStage').textContent=`${error.message}；未通过校验的任务不会删除本地文件。`;toast(error.message,true)}
  $('#progressClose').disabled=false;
}

$('#compact').onclick=()=>location.href='harbor://compact';
$('#refresh').onclick=()=>refresh(true);
$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(runSearch,220)};
$('#clearSearch').onclick=()=>{$('#search').value='';runSearch();$('#search').focus()};
$('#sortBy').onchange=()=>{sortBy=$('#sortBy').value;frozenProjectOrder=null;pinnedInView.clear();renderProjects()};
document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(item=>item.classList.remove('active'));button.classList.add('active');filter=button.dataset.filter;frozenProjectOrder=null;pinnedInView.clear();if(filter!=='recommended'){selected.clear();recommended.clear();$('#recommendedTab').hidden=true}renderProjects();updateSelection()});
$('#selectAll').onclick=()=>{const items=selectRecommended();toast(items.length?`已推荐 ${items.length} 个安全候选，可逐项调整`:'暂时没有符合条件的候选')};
$('#optimize').onclick=async()=>{try{const items=selectRecommended();if(!items.length)throw Error('暂时没有符合 30 天安全条件的已完成历史');await prepareMigration(items,'查看停泊方案 · 本轮建议')}catch(error){toast(error.message,true)}};
$('#offload').onclick=async()=>{try{if(filter==='linked'){$('#manageDialog').showModal();return}await prepareMigration(data.sessions.filter(item=>selected.has(item.path)))}catch(error){toast(error.message,true)}};
$('#progressClose').onclick=()=>$('#progressDialog').close();
$('#openInCodex').onclick=async()=>{
  if(!activeTaskId)return;
  if(!activeTask?.is_subagent){location.href=`codex://threads/${encodeURIComponent(activeTaskId)}`;return}
  const button=$('#openInCodex');button.disabled=true;button.textContent='读取中…';
  try{
    const response=await post('/api/task-record',{id:activeTaskId}),record=response.record;
    $('#taskRecordCount').textContent=`${record.messages.length} 条`;
    $('#taskRecordMessages').innerHTML=record.messages.length?record.messages.map((item,index)=>`<article><span>${index===record.messages.length-1?'最终汇报':'进度记录'}${item.timestamp?` · ${esc(formatDate(item.timestamp))}`:''}</span><p>${esc(item.message)}</p></article>`).join(''):'<div class="record-empty">这个子任务没有留下可展示的对外汇报。</div>';
    $('#taskRecord').hidden=false;$('#taskRecord').scrollIntoView({behavior:'smooth',block:'nearest'});button.textContent='已展开记录';
  }catch(error){toast(error.message,true);button.textContent='查看任务记录'}finally{button.disabled=false}
};
$('#openParentInCodex').onclick=()=>{if(activeTask?.parent_id)location.href=`codex://threads/${encodeURIComponent(activeTask.parent_id)}`};
$('#audit').onclick=async()=>{try{const response=await post('/api/audit',{paths:[...selected]});toast(`已校验 ${response.results.length} 项，${response.results.filter(item=>item.verified).length} 项一致`)}catch(error){toast(error.message,true)}};
$('#restore').onclick=async()=>{try{$('#manageDialog').close();if(!await ask('恢复到本机','<p>把所选停泊历史恢复为内盘普通文件，外置原件仍保留。</p>'))return;await post('/api/restore',{paths:[...selected]});selected.clear();toast('已恢复到本机');await refresh()}catch(error){toast(error.message,true)}};
$('#finalize').onclick=async()=>{try{$('#manageDialog').close();if(!await ask('释放本地副本','<p>这一步会永久删除单独保留的本地副本，才真正腾出空间。外置盘断开时，对应历史将暂时不可读。</p>'))return;await post('/api/finalize',{paths:[...selected],confirmation:'DELETE LOCAL BACKUPS'});selected.clear();toast('本地副本已释放');await refresh()}catch(error){toast(error.message,true)}};

init().catch(error=>toast(error.message,true));

function installProjectStorage(){
  const section=document.createElement('section');section.className='panel project-storage';section.id='projectStorage';
  section.innerHTML='<div class="panel-head"><div><h2>项目文件与历史</h2><p>大素材停泊到外置盘，原项目入口和文件路径继续使用。</p></div><div class="panel-tools"><select id="storageProject" aria-label="选择项目"></select><button id="projectPlanButton">查看项目存储方案</button></div></div><p class="storage-note">只在你查看方案时盘点项目素材；工作文件、环境与既有链接保留原位。</p>';
  document.querySelector('main > .panel').before(section);
  const dialog=document.createElement('dialog');dialog.id='projectFileDialog';dialog.className='project-file-dialog';
  dialog.innerHTML='<span class="task-dialog-kicker">项目存储方案</span><h3 id="projectFileTitle"></h3><div id="projectFileSummary"></div><div class="project-file-tools"><button id="projectFilesSelectAll">全选候选素材</button><button id="downloadProjectPlan">下载文件清单</button><span id="projectFileSelection"></span></div><div id="projectFileList" class="project-file-list"></div><label class="backup-option"><input type="checkbox" id="projectKeepLocal" checked><span><b>同时保留本地副本</b><small>首次停泊建议保留。取消勾选后，逐文件独立复核通过才释放对应实体。</small></span></label><p class="storage-note">U 盘在线时，Codex 仍通过原路径读素材；离线时原始素材暂时不可读。不要在素材停泊时编辑这些文件。</p><form method="dialog"><button value="cancel">关闭</button><button type="button" id="projectFilesDock" class="primary">停泊所选素材</button></form>';
  document.body.append(dialog);
  const management=document.createElement('section');management.id='parkedProjectFiles';management.innerHTML='<details><summary id="parkedProjectSummary">已停泊素材</summary><p class="storage-note">这里管理由新版项目停泊生成、具有校验记录的素材。</p><div id="parkedProjectList" class="project-file-list"></div><div class="project-file-tools"><button id="restoreProjectFiles">恢复所选素材到本机</button><button id="releaseProjectFiles">释放所选素材本地副本</button></div></details>';
  $('#projectFileList').after(management);
  $('#projectPlanButton').onclick=showProjectPlan;
  $('#projectShortcut').onclick=showProjectPlan;
  const paging=document.createElement('div');paging.className='project-file-tools';paging.innerHTML='<button id="projectFilesPrev">上一页</button><span id="projectFilePageLabel"></span><button id="projectFilesNext">下一页</button>';
  $('#projectFileList').after(paging);const groupControls=document.createElement('div');groupControls.id='projectFileGroups';groupControls.className='project-file-tools';$('#projectFileList').before(groupControls);
  $('#projectFilesSelectAll').onclick=()=>{const rows=projectFilePlan?.files.files||[];if(rows.length&&rows.every(row=>selectedProjectFiles.has(row.source)))selectedProjectFiles.clear();else for(const row of rows)selectedProjectFiles.add(row.source);renderProjectFileList()};
  $('#projectFilesPrev').onclick=()=>{projectFilePage--;renderProjectFileList()};$('#projectFilesNext').onclick=()=>{projectFilePage++;renderProjectFileList()};
  $('#downloadProjectPlan').onclick=()=>{if(!projectFilePlan)return;const blob=new Blob([JSON.stringify(projectFilePlan.files,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='memory-harbor-project-files.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
  $('#projectFilesDock').onclick=dockProjectFiles;
  $('#restoreProjectFiles').onclick=()=>manageProjectFiles('restore');$('#releaseProjectFiles').onclick=()=>manageProjectFiles('release');
}
function renderProjectStorage(){
  const select=$('#storageProject');if(!select)return;const previous=select.value;
  select.innerHTML=(data.projects||[]).map(project=>`<option value="${esc(project.id)}">${esc(project.name)}</option>`).join('');
  if([...select.options].some(option=>option.value===previous))select.value=previous;
  $('#projectPlanButton').disabled=operationBusy||!select.options.length;
  $('#projectShortcut').disabled=operationBusy||!select.options.length;
}
async function showProjectPlan(){
  if(operationBusy)return;const button=$('#projectPlanButton');button.disabled=true;button.textContent='正在盘点项目…';
  try{
    if(!$('#volume').value)throw Error('请先选择一个可写外置盘');
    const response=await post('/api/project-plan',{project_id:$('#storageProject').value,volume:$('#volume').value});projectFilePlan=response.plan;projectFilePage=0;selectedProjectFiles.clear();selectedParkedProjectFiles.clear();
    const {project,files,history}=projectFilePlan;
    $('#projectFileTitle').textContent=project.name;
    $('#projectFileSummary').innerHTML=`<p>原入口继续使用：<code>${esc(files.project_root)}</code></p><div class="storage-metrics"><article><span>本机候选素材</span><b>${fmt(files.total_bytes)}</b><small>${files.count} 个文件 · 尚未停泊</small></article><article><span>已停泊任务历史</span><b>${fmt(history.docked_bytes)}</b><small>${history.docked} / ${history.total} 项 · ${history.docked_online} 项在线</small></article></div><p>素材和历史是两部分，不重复累计。历史仍在本机 ${fmt(history.local_bytes)}，其中 ${history.eligible} 项可停泊。</p><p>素材存到 ${esc(projectFilePlan.volume.name)}；项目目录、说明文档、脚本和运行环境继续留在本机。</p><details><summary>为什么有些内容保留在本机？</summary><ul>${files.retained.map(row=>`<li>${esc(row.label)}：${row.count} 个文件</li>`).join('')}<li>本机运行环境：${files.skipped_local_directories} 个目录</li>${history.retained.map(row=>`<li>历史 · ${esc(row.label)}：${row.count} 项</li>`).join('')}</ul><p>历史任务仍在下方“你的历史”列表停泊。主任务与未完成记录继续受保护。</p></details>`;
    $('#projectKeepLocal').checked=true;renderProjectFileList();$('#projectFileDialog').showModal();
  }catch(error){toast(error.message,true)}finally{button.disabled=false;button.textContent='查看项目存储方案'}
}
function renderProjectFileList(){
  const rows=projectFilePlan?.files.files||[];
  projectFilePage=Math.max(0,Math.min(projectFilePage,Math.ceil(rows.length/100)-1));const page=rows.slice(projectFilePage*100,projectFilePage*100+100);
  $('#projectFileList').innerHTML=rows.length?page.map(row=>`<label class="project-file-row"><input type="checkbox" data-project-file="${esc(row.source)}" ${selectedProjectFiles.has(row.source)?'checked':''}><span title="${esc(row.relative)}">${esc(row.relative)}</span><b>${fmt(row.bytes)}</b></label>`).join(''):'<p class="empty">目前没有可以停泊的素材。展开说明查看保留原因。</p>';
  $('#projectFilePageLabel').textContent=`${rows.length?projectFilePage+1:0} / ${Math.ceil(rows.length/100)} 页 · 共 ${rows.length} 个文件`;$('#projectFilesPrev').disabled=projectFilePage<=0;$('#projectFilesNext').disabled=(projectFilePage+1)*100>=rows.length;
  $('#projectFilesSelectAll').textContent=rows.length&&rows.every(row=>selectedProjectFiles.has(row.source))?'取消全部候选素材':'全选候选素材';
  $('#projectFileGroups').innerHTML=(projectFilePlan?.files.groups||[]).filter(group=>group.candidate_count).map(group=>`<button type="button" data-project-file-group="${esc(group.name)}">${esc(group.name)} · ${fmt(group.candidate_bytes)}</button>`).join('');
  document.querySelectorAll('[data-project-file-group]').forEach(button=>button.onclick=()=>{const members=rows.filter(row=>row.group===button.dataset.projectFileGroup),all=members.every(row=>selectedProjectFiles.has(row.source));for(const row of members)all?selectedProjectFiles.delete(row.source):selectedProjectFiles.add(row.source);renderProjectFileList()});
  document.querySelectorAll('[data-project-file]').forEach(control=>control.onchange=()=>{control.checked?selectedProjectFiles.add(control.dataset.projectFile):selectedProjectFiles.delete(control.dataset.projectFile);updateProjectFileSelection()});updateProjectFileSelection();
  const parked=projectFilePlan?.files.parked_files||[];$('#parkedProjectSummary').textContent=`现有素材链接 · ${parked.length} 个`;
  $('#parkedProjectList').innerHTML=parked.length?parked.map(row=>`<label class="project-file-row"><input type="checkbox" data-parked-project-file="${esc(row.source)}" ${selectedParkedProjectFiles.has(row.source)?'checked':''} ${row.restorable?'':'disabled'}><span title="${esc(row.relative)}">${esc(row.relative)}</span><b>${row.restorable?'可管理':'旧链接保留'}</b></label>`).join(''):'<p class="empty">没有已停泊素材链接</p>';
  document.querySelectorAll('[data-parked-project-file]').forEach(control=>control.onchange=()=>{control.checked?selectedParkedProjectFiles.add(control.dataset.parkedProjectFile):selectedParkedProjectFiles.delete(control.dataset.parkedProjectFile);$('#restoreProjectFiles').disabled=$('#releaseProjectFiles').disabled=!selectedParkedProjectFiles.size});
  $('#restoreProjectFiles').disabled=$('#releaseProjectFiles').disabled=!selectedParkedProjectFiles.size;
}
function updateProjectFileSelection(){
  const rows=(projectFilePlan?.files.files||[]).filter(row=>selectedProjectFiles.has(row.source));
  $('#projectFileSelection').textContent=`已选 ${rows.length} 个 · ${fmt(rows.reduce((sum,row)=>sum+row.bytes,0))}`;$('#projectFilesDock').disabled=operationBusy||!rows.length;
}
async function dockProjectFiles(){
  if(operationBusy||!projectFilePlan)return;
  const frozen=projectFilePlan,rows=frozen.files.files.filter(row=>selectedProjectFiles.has(row.source)),keepLocal=$('#projectKeepLocal').checked;
  if(!rows.length)return;operationBusy=true;$('#projectFileDialog').close();updateSelection();renderProjectStorage();
  try{
    if(!await ask('确认停泊项目素材',`<p>将停泊 ${rows.length} 个素材，共 ${fmt(rows.reduce((sum,row)=>sum+row.bytes,0))}，存到 ${esc(frozen.volume.name)}。</p><p>原入口和文件路径保留。${keepLocal?'本机副本继续保留，本次不释放对应空间。':'独立复核通过后释放对应本机实体。'}</p>`))return;
    const total=rows.reduce((sum,row)=>sum+row.bytes,0);let completed=0,bytes=0;$('#progressClose').disabled=true;$('#progressTitle').textContent='正在停泊项目素材';setProgress(0,rows.length,0,total,'准备逐文件复制与校验…');$('#progressDialog').showModal();
    try{
      for(const row of rows){setProgress(completed,rows.length,bytes,total,row.relative);await post('/api/project-file-offload',{plan_id:frozen.plan_id,path:row.source,volume:frozen.volume.path,keep_local:keepLocal,confirmation:'DOCK PROJECT FILE'});completed++;bytes+=row.bytes}
      setProgress(completed,rows.length,bytes,total,keepLocal?'素材已停泊，本地副本已保留':'素材已停泊，对应本地空间已释放');toast('项目素材停泊完成，原路径继续可用');await refresh();
    }catch(error){$('#progressTitle').textContent='停泊已停止';setProgress(completed,rows.length,bytes,total,`已完成 ${completed} 项；${error.message}`);toast(error.message,true)}finally{$('#progressClose').disabled=false}
  }finally{operationBusy=false;updateSelection();renderProjectStorage()}
}
async function manageProjectFiles(action){
  if(operationBusy||!projectFilePlan||!selectedParkedProjectFiles.size)return;
  const frozen=projectFilePlan,paths=[...selectedParkedProjectFiles],restore=action==='restore';operationBusy=true;$('#projectFileDialog').close();renderProjectStorage();
  try{
    if(!await ask(restore?'恢复项目素材':'释放项目素材本地副本',`<p>处理 ${paths.length} 个所选素材。${restore?'校验外部实体后恢复为本机普通文件，外部副本保留。':'重新核对外部实体、校验记录和本地副本，全部一致后才释放对应副本。'}</p>`))return;
    $('#progressClose').disabled=true;$('#progressTitle').textContent=restore?'正在恢复项目素材':'正在释放本地副本';$('#progressDialog').showModal();let count=0;setProgress(0,paths.length,0,0,'准备校验…');
    try{
      for(const path of paths){await post(restore?'/api/project-file-restore':'/api/project-file-offload',{plan_id:frozen.plan_id,path,volume:frozen.volume.path,keep_local:false,confirmation:restore?'RESTORE PROJECT FILE':'DOCK PROJECT FILE'});count++;setProgress(count,paths.length,0,0,path.split('/').pop())}
      $('#progressStage').textContent=restore?'所选素材已恢复到本机':'所选素材本地副本已处理';toast('处理完成');await refresh();
    }catch(error){$('#progressTitle').textContent='处理已停止';$('#progressStage').textContent=`已完成 ${count} 项；${error.message}`;toast(error.message,true)}finally{$('#progressClose').disabled=false}
  }finally{operationBusy=false;updateSelection();renderProjectStorage()}
}
