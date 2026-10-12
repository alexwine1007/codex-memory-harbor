/* One local workbench. All mutations use the existing server-owned safety plans. */
let token='',data=null,config={},filter='eligible',sortBy='size',busy=false,activeTask=null;
let searchResults=null,searchGeneration=0,searchTimer=0,toastTimer=0,groupOrder=[];
const selected=new Set(),selectedFiles=new Set(),selectedParkedFiles=new Set(),expanded=new Set(),plans=new Map(),pages=new Map(),scanning=new Set();
const taskLabels=new Map(),labelQueue=new Set(),labelPending=new Set();let labelObserver=null,labelsRunning=false;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmt=bytes=>{let value=Number(bytes)||0,index=0,units=['B','KB','MB','GB','TB'];while(value>=1024&&index<4){value/=1024;index++}return`${value.toFixed(index&&value<10?1:0)} ${units[index]}`};
function preference(key,fallback){try{return localStorage.getItem('harbor.'+key)||fallback}catch{return fallback}}
function savePreference(key,value){try{localStorage.setItem('harbor.'+key,value)}catch{/* Storage disabled; session preference still works. */}}
let language=HarborI18n.normalize(preference('language',navigator.language)),theme=preference('theme','system');
const t=(key,values)=>HarborI18n.translate(language,key,values);
function localize(){
  document.documentElement.lang=language;
  document.querySelectorAll('[data-i18n]').forEach(element=>element.textContent=t(element.dataset.i18n));
  document.querySelectorAll('[data-placeholder]').forEach(element=>element.placeholder=t(element.dataset.placeholder));
  document.querySelectorAll('[data-aria]').forEach(element=>element.setAttribute('aria-label',t(element.dataset.aria)));
  $('#language').value=language;$('#theme').value=theme;
  applyTheme();
}
function applyTheme(){document.documentElement.dataset.theme=theme==='system'?(matchMedia('(prefers-color-scheme:light)').matches?'light':'dark'):theme;}
function toast(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').classList.add('show');toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4000)}
function errorView(error){return`<p>${esc(t('errorHint'))}</p><details><summary>${esc(t('technical'))}</summary><p>${esc(error.message)}</p></details>`}
function showError(error){if($('#dialog').open||$('#progressDialog').open){toast(t('errorHint'));return}ask(t('failed'),errorView(error),false)}
async function read(url){const response=await fetch(url);if(!response.ok)throw Error(t('unavailable'));return response.json()}
async function post(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Harbor-Token':token},body:JSON.stringify(body)});const json=await response.json();if(!response.ok||!json.ok)throw Error(json.error||t('failed'));return json}
function ask(title,html,confirmation=true){$('#dialogTitle').textContent=title;$('#dialogBody').innerHTML=html;$('#confirmAction').hidden=!confirmation;const dialog=$('#dialog');dialog.returnValue='';dialog.showModal();return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='ok'),{once:true}))}
function protectedProject(path){return(config.protected_projects||[]).some(project=>path===project||path.startsWith(project+'/'))}
function fileRows(){return[...plans.values()].flatMap(plan=>plan.files.files)}
function currentHistory(){return(data?.sessions||[]).filter(row=>selected.has(row.path))}
function storage(){
  const volumes=(data?.volumes||[]).filter(row=>row.writable),old=$('#volume').value,current=volumes.find(row=>row.path===old)||volumes[0];
  const next=current?.path||'';
  if(old&&old!==next){plans.clear();selectedFiles.clear();selectedParkedFiles.clear()}
  $('#volume').value=next;$('#driveName').textContent=current?t('driveOnline',{name:current.name,free:current.free_h}):t('driveOffline');$('#driveDot').classList.toggle('offline',!current);
  $('#driveMenu').innerHTML=volumes.map(row=>`<button class="drive-option ${row.path===next?'active':''}" data-volume="${esc(row.path)}"><span><b>${esc(row.name)}</b><small>${esc(row.free_h)}</small></span><span>${row.path===next?'✓':''}</span></button>`).join('')+`<button class="drive-option" disabled>${esc(t('cloudFuture'))}</button>`;
  document.querySelectorAll('[data-volume]').forEach(button=>button.onclick=()=>{if(busy)return;if(button.dataset.volume!==$('#volume').value){plans.clear();selectedFiles.clear();selectedParkedFiles.clear()}$('#volume').value=button.dataset.volume;storage();render()});
}
async function refresh(resetOrder=true){
  if(busy)return;$('#refresh').disabled=true;
  try{data=await read('/api/scan?'+new URLSearchParams({min_age:30}));taskLabels.clear();labelQueue.clear();HarborWorkbench.pruneSelection(data.sessions,selected);if(resetOrder)groupOrder=[];storage();if(!expanded.size){const first=groups()[0];if(first)expanded.add(first.key)}render()}finally{$('#refresh').disabled=false}
}
async function syncVolumes(){try{if(!data)return;const result=await read('/api/volumes');data.volumes=result.volumes||[];storage();render();if(!busy){const repaired=await post('/api/repair-links',{});if(repaired.repaired?.length)await refresh(false)}}catch{toast(t('unavailable'))}}
window.harborVolumeChanged=syncVolumes;
function items(){
  if(!searchResults)return data.sessions;
  const matches=new Map(searchResults.map(row=>[row.source_path,row]));
  return searchResults.map(row=>{const current=data.sessions.find(item=>item.path===row.source_path);return current?{...current,match_excerpt:row.match_excerpt}:{path:row.source_path,id:row.thread_id,title:row.title,project_id:row.project_id,project_name:row.project_name,project_path:row.project_path,cwd:row.cwd,kind:row.kind||'child',logical:Number(row.logical)||0,linked:row.linked,target_exists:row.target_available,catalog_only:true,match_excerpt:matches.get(row.source_path)?.match_excerpt}});
}
function visibleItems(group){return HarborWorkbench.sortItems(group.items.filter(row=>searchResults!==null||filter==='all'||(filter==='eligible'?row.eligible:row.linked)),sortBy)}
function groupFiles(group){const plan=plans.get(group.key);return filter==='linked'?(plan?.files.parked_files||[]).filter(row=>row.restorable):plan?.files.files||[]}
function groups(){
  const map=new Map();
  if(!searchResults)for(const project of data.projects||[])map.set(project.id,{key:project.id,name:project.name,path:project.path||project.roots?.[0]||'',items:[],standalone:false});
  for(const row of items()){const key=row.project_id||'__standalone__';const group=map.get(key)||{key,name:row.project_id?(row.project_name||t('unnamedProject')):t('standalone'),path:row.project_path||row.cwd||'',items:[],standalone:!row.project_id};group.items.push(row);map.set(key,group)}
  const result=[...map.values()].filter(group=>visibleItems(group).length||(!searchResults&&!group.standalone));
  const size=group=>visibleItems(group).reduce((sum,row)=>sum+(row.logical||0),0)+(filter==='linked'?0:plans.get(group.key)?.files.total_bytes||0);
  const age=group=>Math.max(-1,...visibleItems(group).map(row=>row.age_days??-1));
  result.sort((a,b)=>sortBy==='recent'?age(b)-age(a)||size(b)-size(a):size(b)-size(a)||age(b)-age(a));
  if(!groupOrder.length)groupOrder=result.map(group=>group.key);else{const order=new Map(groupOrder.map((key,index)=>[key,index]));result.sort((a,b)=>(order.get(a.key)??1e9)-(order.get(b.key)??1e9))}
  return result;
}
function taskState(row){return row.catalog_only?(row.target_exists?'docked':'indexOnly'):row.protected_session||row.protected_project?'protected':row.linked?(row.target_exists?'docked':'offline'):row.kind==='main'?'main':!row.last_turn_complete?'active':row.eligible?'candidate':'recent'}
function taskRow(row){
  const selectable=!row.catalog_only&&(filter==='linked'?row.linked:row.eligible),state=taskState(row),info=HarborWorkbench.taskPresentation(row,taskLabels.get(row.id),t);
  return`<div class="task-row"><input type="checkbox" data-task="${esc(row.path)}" aria-label="${esc(info.title)}" ${selected.has(row.path)?'checked':''} ${selectable&&!busy?'':'disabled'}><button class="task-name" data-task-detail="${esc(row.id||'')}" title="${esc(info.title+' — '+info.summary)}"><b>${esc(info.title)}</b><span>${esc(info.summary)}</span></button><span class="task-size">${fmt(row.logical)}</span><span class="task-age">${row.age_days==null?'':esc(t('modified',{days:row.age_days}))}</span><span class="task-state">${esc(t(state))}</span><button class="pin ${row.protected_session?'on':''}" data-pin-task="${esc(row.id||'')}" aria-label="${esc(t(row.protected_session?'unpinTask':'pinTask'))}" ${row.id&&!busy?'':'disabled'}>${row.protected_session?'★':'☆'}</button></div>`;
}
function observeTaskLabels(){
  labelObserver?.disconnect();
  // Only rows entering the viewport are queued; never a whole-archive background scan.
  const rows=new Map(items().map(row=>[row.id,row]));
  const enqueue=button=>{const id=button.dataset.taskDetail,row=rows.get(id);if(id&&row&&!row.task_label_ready&&!taskLabels.has(id)&&!labelPending.has(id)){labelQueue.add(id);loadTaskLabels()}};
  if(typeof IntersectionObserver==='undefined')return; // Details remain an on-demand fallback.
  labelObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){labelObserver.unobserve(entry.target);enqueue(entry.target)}},{rootMargin:'120px'});
  document.querySelectorAll('[data-task-detail]').forEach(button=>labelObserver.observe(button));
}
async function loadTaskLabels(){
  if(labelsRunning||busy||!labelQueue.size)return;labelsRunning=true;
  const ids=[...labelQueue].slice(0,4);ids.forEach(id=>{labelQueue.delete(id);labelPending.add(id)});
  try{
    const result=await post('/api/task-labels',{ids});
    for(const label of result.labels){const row=items().find(row=>row.id===label.id);if(row&&(!row.label_signature||!label.signature||row.label_signature===label.signature))taskLabels.set(label.id,label)}
  }catch{for(const id of ids)taskLabels.set(id,{task_label_ready:true})}
  finally{
    labelsRunning=false;ids.forEach(id=>labelPending.delete(id));
    // Update text in place: no rerender, reordering, focus loss or selection change.
    const rows=new Map(items().map(row=>[row.id,row]));
    for(const button of document.querySelectorAll('[data-task-detail]')){const id=button.dataset.taskDetail,row=rows.get(id);if(!row||!ids.includes(id))continue;const info=HarborWorkbench.taskPresentation(row,taskLabels.get(id),t);button.querySelector('b').textContent=info.title;button.querySelector('span').textContent=info.summary;button.title=info.title+' — '+info.summary;button.parentElement.querySelector('input').setAttribute('aria-label',info.title)}
    if(labelQueue.size)loadTaskLabels();
  }
}
function mediaView(group){
  if(group.standalone||searchResults)return'';
  const plan=plans.get(group.key),protectedOn=protectedProject(group.path),loading=scanning.has(group.key);
  const button=`<button data-scan-media="${esc(group.key)}" ${busy||loading||protectedOn?'disabled':''}>${esc(t(loading?'loading':'inspectMedia'))}</button>`;
  if(!plan)return`<section class="media-section"><div class="media-tools"><b>${esc(t('media'))}</b>${button}</div><p class="media-note">${esc(t(protectedOn?'mediaProtected':'mediaUnscanned'))}</p></section>`;
  const all=plan.files.files,parked=plan.files.parked_files||[],rows=filter==='linked'?parked:all,page=pages.get(group.key)||0,shown=rows.slice(page*100,page*100+100);
  return`<section class="media-section"><div class="media-tools"><b>${esc(t('media'))}</b>${button}<button data-export="${esc(group.key)}">${esc(t('export'))}</button></div><p class="media-note">${esc(t('mediaSummary',{count:all.length,size:fmt(plan.files.total_bytes),history:fmt(plan.history.docked_bytes)}))}</p><div class="media-tools">${filter!=='linked'?`<button data-files-all="${esc(group.key)}" ${busy||!all.length?'disabled':''}>${esc(t(all.length&&all.every(row=>selectedFiles.has(row.source))?'clearSelection':'selectAll'))}</button>`:''}${(filter!=='linked'?plan.files.groups||[]:[]).filter(row=>row.candidate_count).map(row=>`<button data-files-group="${esc(group.key)}" data-folder="${esc(row.name)}">${esc(row.name)} · ${fmt(row.candidate_bytes)}</button>`).join('')}</div><div class="file-list">${shown.length?shown.map(row=>`<label class="file-row"><input type="checkbox" ${filter==='linked'?'data-parked-file':'data-file'}="${esc(row.source)}" aria-label="${esc(row.relative)}" ${(filter==='linked'?selectedParkedFiles:selectedFiles).has(row.source)?'checked':''} ${busy||filter==='linked'&&!row.restorable?'disabled':''}><span title="${esc(row.relative)}">${esc(row.relative)}</span><b>${filter==='linked'?esc(t(row.restorable?'docked':'legacyLink')):fmt(row.bytes)}</b></label>`).join(''):`<p class="empty">${esc(t('mediaEmpty'))}</p>`}</div>${rows.length>100?`<div class="media-tools"><button data-page="${esc(group.key)}" data-step="-1" ${page<=0?'disabled':''}>${esc(t('prev'))}</button><span>${esc(t('page',{page:page+1,pages:Math.ceil(rows.length/100)}))}</span><button data-page="${esc(group.key)}" data-step="1" ${(page+1)*100>=rows.length?'disabled':''}>${esc(t('next'))}</button></div>`:''}</section>`;
}
function render(){
  if(!data)return;$('#free').textContent=data.disk.free_h;
  const total=data.totals,media=[...plans.values()].reduce((sum,plan)=>sum+plan.files.total_bytes,0);
  $('#inventorySummary').textContent=t(plans.size?'inventoryMedia':'inventory',{count:total.eligible_files,size:total.eligible_h,media:fmt(media)});
  $('#catalogStatus').textContent=t('catalog',{count:data.catalog?.items??total.files,version:config.version});
  const projectGroups=groups();
  $('#projects').innerHTML=projectGroups.length?projectGroups.map(group=>{
    const rows=visibleItems(group),can=rows.filter(row=>!row.catalog_only&&(filter==='linked'?row.linked:row.eligible)),files=groupFiles(group),fileSet=filter==='linked'?selectedParkedFiles:selectedFiles,count=can.length+files.length,all=count&&can.every(row=>selected.has(row.path))&&files.every(row=>fileSet.has(row.source)),partial=(can.some(row=>selected.has(row.path))||files.some(row=>fileSet.has(row.source)))&&!all,open=expanded.has(group.key),pin=protectedProject(group.path);
    const mediaPlan=plans.get(group.key),size=rows.reduce((sum,row)=>sum+(row.logical||0),0)+(filter==='linked'?0:mediaPlan?.files.total_bytes||0),knownCapacity=(filter==='linked'&&files.length)||(!rows.length&&!mediaPlan)?'—':fmt(size),capacityScope=pin?'protected':group.standalone?'standalone':mediaPlan?'inspected':rows.length?'historyAmount':'unscanned';
    return`<section class="tree-group"><div class="project"><button class="disclosure ${open?'open':''}" data-expand="${esc(group.key)}" aria-label="${esc(t(open?'collapse':'expand'))}" aria-expanded="${open}">›</button><input type="checkbox" data-project="${esc(group.key)}" data-partial="${partial}" aria-label="${esc(group.name)}" ${all?'checked':''} ${count&&!busy?'':'disabled'}><button class="project-name" data-expand="${esc(group.key)}"><b>${esc(group.name)}</b><span>${esc(group.standalone?t('standaloneNote'):group.path)}</span></button><b class="project-size">${knownCapacity}</b><span class="badge">${esc(t(capacityScope))}</span>${group.standalone?'':`<button class="pin ${pin?'on':''}" data-pin-project="${esc(group.path)}" aria-label="${esc(t(pin?'unpinProject':'pinProject'))}" ${busy?'disabled':''}>${pin?'★':'☆'}</button>`}</div>${open?`<div class="tree-children">${rows.map(taskRow).join('')}${mediaView(group)}</div>`:''}</section>`;
  }).join(''):`<p class="empty">${esc(t(searchResults?'noResults':'empty'))}</p>`;
  $('#searchStatus').hidden=searchResults===null;if(searchResults)$('#searchStatus').textContent=t('searchCount',{count:searchResults.length});
  document.querySelectorAll('[data-partial="true"]').forEach(element=>element.indeterminate=true);
  bindTree();updateSelection();observeTaskLabels();
}
function bindTree(){
  document.querySelectorAll('[data-expand]').forEach(button=>button.onclick=()=>{const key=button.dataset.expand;expanded.has(key)?expanded.delete(key):expanded.add(key);render()});
  document.querySelectorAll('[data-project]').forEach(control=>control.onchange=()=>{const group=groups().find(row=>row.key===control.dataset.project);for(const row of visibleItems(group).filter(row=>!row.catalog_only&&(filter==='linked'?row.linked:row.eligible)))control.checked?selected.add(row.path):selected.delete(row.path);const set=filter==='linked'?selectedParkedFiles:selectedFiles;for(const row of groupFiles(group))control.checked?set.add(row.source):set.delete(row.source);render()});
  document.querySelectorAll('[data-task]').forEach(control=>control.onchange=()=>{control.checked?selected.add(control.dataset.task):selected.delete(control.dataset.task);render()});
  document.querySelectorAll('[data-task-detail]').forEach(button=>button.onclick=()=>showTask(button.dataset.taskDetail));
  document.querySelectorAll('[data-pin-task]').forEach(button=>button.onclick=()=>pin('session',button.dataset.pinTask));
  document.querySelectorAll('[data-pin-project]').forEach(button=>button.onclick=()=>pin('project',button.dataset.pinProject));
  document.querySelectorAll('[data-scan-media]').forEach(button=>button.onclick=()=>inspectMedia(button.dataset.scanMedia));
  document.querySelectorAll('[data-file],[data-parked-file]').forEach(control=>control.onchange=()=>{const set=control.dataset.file?selectedFiles:selectedParkedFiles,path=control.dataset.file||control.dataset.parkedFile;control.checked?set.add(path):set.delete(path);render()});
  document.querySelectorAll('[data-files-all],[data-files-group]').forEach(button=>button.onclick=()=>{const plan=plans.get(button.dataset.filesAll||button.dataset.filesGroup),rows=plan.files.files.filter(row=>!button.dataset.folder||row.group===button.dataset.folder),all=rows.every(row=>selectedFiles.has(row.source));for(const row of rows)all?selectedFiles.delete(row.source):selectedFiles.add(row.source);render()});
  document.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>{pages.set(button.dataset.page,(pages.get(button.dataset.page)||0)+Number(button.dataset.step));render()});
  document.querySelectorAll('[data-export]').forEach(button=>button.onclick=()=>{const blob=new Blob([JSON.stringify(plans.get(button.dataset.export).files,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='memory-harbor-project-files.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
}
function updateSelection(){
  const histories=currentHistory(),files=fileRows().filter(row=>selectedFiles.has(row.source)),count=histories.length+files.length+selectedParkedFiles.size;
  $('#selected').textContent=count?t('selected',{history:histories.length,files:files.length+selectedParkedFiles.size}):t('selectContent');
  $('#selectedSize').textContent=selectedParkedFiles.size?'—':fmt(histories.reduce((sum,row)=>sum+(row.backup_exists?row.backup_bytes:row.logical),0)+files.reduce((sum,row)=>sum+row.bytes,0));
  const manage=histories.some(row=>row.linked)||selectedParkedFiles.size;
  $('#offload').textContent=t(busy?'busy':manage?'manage':'review');$('#offload').disabled=busy||scanning.size>0||!count||!$('#volume').value;
  const candidates=HarborWorkbench.recommendedItems(data.sessions),knownFiles=fileRows();
  $('#selectAll').disabled=busy||filter!=='eligible'||searchResults!==null||!candidates.length&&!knownFiles.length;
  $('#selectAll').textContent=t(candidates.length+knownFiles.length&&candidates.every(row=>selected.has(row.path))&&knownFiles.every(row=>selectedFiles.has(row.source))?'clearSelection':'selectAll');
  $('#language').disabled=$('#theme').disabled=$('#sortBy').disabled=busy;$('#audit').disabled=selectedParkedFiles.size>0;
  document.querySelectorAll('[data-filter]').forEach(button=>button.disabled=busy);
}
async function pin(scope,value){
  if(busy||!value)return;const enabled=scope==='project'?!protectedProject(value):!(config.protected_sessions||[]).includes(value);busy=true;render();
  try{const response=await post('/api/protect',{scope,value,enabled});config={...config,...response.settings};plans.clear();selectedFiles.clear();selectedParkedFiles.clear();busy=false;await refresh(false);toast(t('pinned'))}catch(error){showError(error)}finally{busy=false;render()}
}
async function inspectMedia(id){
  if(busy||scanning.has(id))return;if(!$('#volume').value){showError(Error(t('chooseDrive')));return}
  const volume=$('#volume').value;scanning.add(id);render();
  try{const response=await post('/api/project-plan',{project_id:id,volume});if(volume!==$('#volume').value)return;const previous=plans.get(id);for(const row of previous?.files.files||[])selectedFiles.delete(row.source);for(const row of previous?.files.parked_files||[])selectedParkedFiles.delete(row.source);plans.set(id,response.plan);pages.set(id,0)}catch(error){showError(error)}finally{scanning.delete(id);render()}
}
async function search(){
  const generation=++searchGeneration,query=$('#search').value.trim();$('#clearSearch').hidden=!query;
  if(!query){searchResults=null;render();return}
  try{const response=await read('/api/recall?'+new URLSearchParams({q:query,limit:100}));if(generation!==searchGeneration||query!==$('#search').value.trim())return;searchResults=response.results||[];for(const row of searchResults)expanded.add(row.project_id||'__standalone__');render()}catch(error){if(generation===searchGeneration)showError(error)}
}
async function prepareMigration(){
  if(busy)return;busy=true;render();
  try{
    if(!$('#volume').value)throw Error(t('chooseDrive'));
    const histories=currentHistory();if(histories.some(row=>row.linked)||selectedParkedFiles.size){if(histories.some(row=>!row.linked)||selectedFiles.size)throw Error(t('noMixedLinked'));$('#manageDialog').showModal();return}
    const objects=HarborWorkbench.selectedObjects(data.sessions,[...plans.values()],selected,selectedFiles);if(!objects.length)throw Error(t('chooseContent'));
    const response=await post('/api/parking-plan',{objects,volume:$('#volume').value}),plan=response.plan,hasFiles=plan.file_count>0;
    const confirmed=await ask(t('confirmDock'),`<p>${esc(t('dockPlan',{history:plan.history_count,files:plan.file_count,size:fmt(plan.bytes),drive:plan.volume_name}))}</p><p>${esc(t('dockContract'))}</p><label class="backup-option"><input id="keepLocalBackup" type="checkbox" ${hasFiles?'checked':''}><span><b>${esc(t('keepBackup'))}</b><small>${esc(t('backupNote'))}</small></span></label>`);
    if(!confirmed)return;await executeMigration(plan,Boolean($('#keepLocalBackup').checked));
  }catch(error){showError(error)}finally{busy=false;render()}
}
function progress(job,totalBytes){
  const state=HarborProgress.state(job,fmt,t);$('#progressFill').value=state.percent;$('#progressFill').setAttribute('aria-valuetext',t('progressVerified',{percent:Math.round(state.percent),count:state.completed}));$('#progressCount').textContent=`${state.completed} / ${state.total}`;$('#progressBytes').textContent=`${fmt(job.bytes)} / ${fmt(totalBytes)}`;$('#progressTitle').textContent=state.title;$('#progressStage').textContent=t(job.phase==='complete'?'completePhase':job.phase||'progressRunning');return state;
}
async function executeMigration(plan,keepLocal){
  $('#progressClose').disabled=true;$('#transferReport').hidden=true;progress({completed:0,total:plan.count,status:'running',bytes:0},plan.bytes);$('#progressDialog').showModal();
  try{
    const response=await post('/api/parking-start',{plan_id:plan.plan_id,volume:$('#volume').value,keep_local:keepLocal,confirmation:'DOCK SELECTED OBJECTS'});let job,state;
    do{job=await read('/api/parking-job?'+new URLSearchParams({id:response.job_id}));state=progress(job,job.total_bytes);if(job.status==='failed')throw Error(job.error);if(job.status==='running')await new Promise(resolve=>setTimeout(resolve,700))}while(job.status==='running');
    if(!state.complete)throw Error(t('planExpired'));$('#progressStage').textContent=state.detail;
    const metrics=job.metrics||{},seconds=metrics.end_to_end_seconds||metrics.elapsed_seconds||0;
    $('#transferReport').hidden=false;$('#transferDetails').innerHTML=`<p>${esc(t('timing',{seconds:seconds.toFixed(1),rate:(job.bytes/Math.max(seconds,.001)/1048576).toFixed(1)}))}</p><p>${esc(t('capacityNote'))}</p><p>${esc(t('offlineNote'))}</p>`;
    selected.clear();selectedFiles.clear();selectedParkedFiles.clear();plans.clear();busy=false;await refresh();busy=true;
  }catch(error){$('#progressTitle').textContent=t('failed');$('#progressStage').textContent=t('errorHint');$('#transferReport').hidden=false;$('#transferDetails').innerHTML=errorView(error)}finally{$('#progressClose').disabled=false}
}
async function showTask(id){
  if(!id||busy)return;
  try{const response=await post('/api/task-detail',{id});activeTask=response.task;const task=activeTask;$('#taskDetailTitle').textContent=task.title||t('unnamedTask');$('#taskDetailPreview').textContent=task.preview||t('taskNoPreview');$('#taskDetailMeta').innerHTML=[['updated',task.updated_at_ms?new Intl.DateTimeFormat(language,{dateStyle:'medium',timeStyle:'short'}).format(new Date(task.updated_at_ms)):t('unknown')],['cwd',task.cwd||t('unknown')],['taskId',task.id],['agent',task.agent_nickname||'—']].map(([key,value])=>`<div><span>${esc(t(key))}</span><b>${esc(value)}</b></div>`).join('');$('#taskRecord').hidden=true;$('#taskRecordMessages').innerHTML='';$('#openParentInCodex').hidden=!task.is_subagent;$('#openInCodex').textContent=t(task.is_subagent?'readReports':'openCodex');$('#taskDetailHint').textContent=t(task.is_subagent?'childHint':'taskHint');$('#taskDialog').showModal()}catch(error){showError(error)}
  if($('#taskDialog').open&&activeTask?.id===id){const key={instruction:'taskSourceInstruction',report:'taskSourceReport',codex:'taskSourceCodex'}[activeTask.summary_source];if(key)$('#taskDetailHint').textContent=t(key,{line:activeTask.source_line})+' '+$('#taskDetailHint').textContent;}
}
async function manage(action){
  if(busy)return;$('#manageDialog').close();busy=true;render();
  try{
    const histories=currentHistory().filter(row=>row.linked),paths=histories.map(row=>row.path),media=[...plans.values()].flatMap(plan=>(plan.files.parked_files||[]).filter(row=>selectedParkedFiles.has(row.source)).map(row=>({plan,row})));if(!paths.length&&!media.length)throw Error(t('chooseContent'));
    if(action==='audit'){const result=paths.length?await post('/api/audit',{paths}):{results:[]};toast(t('auditResult',{count:result.results.length,verified:result.results.filter(row=>row.verified).length}));return}
    if(!await ask(t(action==='restore'?'restore':'release'),`<p>${esc(t('selected',{history:paths.length,files:media.length}))}</p><p>${esc(t(action==='restore'?'restoreNote':'releaseNote'))}</p>`))return;
    $('#progressClose').disabled=true;$('#transferReport').hidden=true;$('#progressTitle').textContent=t(action==='restore'?'restore':'release');$('#progressStage').textContent=t(action==='restore'?'restoreNote':'releaseNote');$('#progressFill').value=0;$('#progressCount').textContent=`0 / ${paths.length+media.length}`;$('#progressBytes').textContent='—';$('#progressDialog').showModal();let completed=0;
    if(paths.length){await post(action==='restore'?'/api/restore':'/api/finalize',{paths,confirmation:'DELETE LOCAL BACKUPS'});completed=paths.length;$('#progressCount').textContent=`${completed} / ${paths.length+media.length}`}
    for(const {plan,row} of media){await post(action==='restore'?'/api/project-file-restore':'/api/project-file-offload',{plan_id:plan.plan_id,path:row.source,volume:plan.volume.path,keep_local:false,confirmation:action==='restore'?'RESTORE PROJECT FILE':'DOCK PROJECT FILE'});completed++;$('#progressCount').textContent=`${completed} / ${paths.length+media.length}`;$('#progressFill').value=Math.min(99,100*completed/(paths.length+media.length))}
    $('#progressFill').value=100;$('#progressTitle').textContent=t('success');$('#progressStage').textContent=t(action==='restore'?'restoreNote':'releaseNote');
    selected.clear();selectedParkedFiles.clear();selectedFiles.clear();plans.clear();busy=false;await refresh();toast(t('success'));
  }catch(error){if($('#progressDialog').open){$('#progressTitle').textContent=t('failed');$('#progressStage').textContent=t('errorHint');$('#transferReport').hidden=false;$('#transferDetails').innerHTML=errorView(error)}else showError(error)}finally{busy=false;$('#progressClose').disabled=false;render()}
}
$('#settings').onclick=$('#drivePicker').onclick=()=>$('#settingsDialog').showModal();
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$('#'+button.dataset.close).close());
$('#language').onchange=()=>{language=$('#language').value;savePreference('language',language);localize();storage();render()};
$('#theme').onchange=()=>{theme=$('#theme').value;savePreference('theme',theme);applyTheme()};
matchMedia('(prefers-color-scheme:light)').addEventListener('change',()=>{if(theme==='system')applyTheme()});
$('#compact').onclick=()=>location.href='harbor://compact';
$('#refresh').onclick=()=>refresh().catch(showError);
$('#search').oninput=()=>{clearTimeout(searchTimer);++searchGeneration;searchTimer=setTimeout(search,220)};
$('#clearSearch').onclick=()=>{clearTimeout(searchTimer);$('#search').value='';search();$('#search').focus()};
$('#sortBy').onchange=()=>{sortBy=$('#sortBy').value;groupOrder=[];render()};
document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{if(busy)return;filter=button.dataset.filter;selected.clear();selectedFiles.clear();selectedParkedFiles.clear();pages.clear();groupOrder=[];document.querySelectorAll('[data-filter]').forEach(control=>control.classList.toggle('active',control===button));render()});
$('#selectAll').onclick=()=>{const candidates=HarborWorkbench.recommendedItems(data.sessions),files=fileRows(),all=candidates.length+files.length&&candidates.every(row=>selected.has(row.path))&&files.every(row=>selectedFiles.has(row.source));for(const row of candidates)all?selected.delete(row.path):selected.add(row.path);for(const row of files)all?selectedFiles.delete(row.source):selectedFiles.add(row.source);render()};
$('#offload').onclick=prepareMigration;
$('#progressClose').onclick=()=>$('#progressDialog').close();
$('#progressDialog').addEventListener('cancel',event=>{if(busy)event.preventDefault()});
$('#openParentInCodex').onclick=()=>{if(activeTask?.parent_id)location.href=`codex://threads/${encodeURIComponent(activeTask.parent_id)}`};
$('#openInCodex').onclick=async()=>{if(!activeTask)return;if(!activeTask.is_subagent){location.href=`codex://threads/${encodeURIComponent(activeTask.id)}`;return}const button=$('#openInCodex');button.disabled=true;try{const result=await post('/api/task-record',{id:activeTask.id});$('#taskRecordMessages').innerHTML=result.record.messages.length?result.record.messages.map(row=>`<article><span>${esc(t('report'))}</span><p>${esc(row.message)}</p></article>`).join(''):`<p>${esc(t('noReports'))}</p>`;$('#taskRecord').hidden=false}catch(error){showError(error)}finally{button.disabled=false}};
$('#audit').onclick=()=>manage('audit');$('#restore').onclick=()=>manage('restore');$('#finalize').onclick=()=>manage('release');
document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){if(document.querySelector('dialog[open]'))return;event.preventDefault();$('#search').focus()}});
localize();
(async()=>{config=await read('/api/config');token=config.token;await refresh()})().catch(showError);
