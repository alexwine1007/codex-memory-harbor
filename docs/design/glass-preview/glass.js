/* Fixture-only design review. No network, storage scanning, timers or file mutations. */
const $ = selector => document.querySelector(selector);
let connected = true;
const examples = [
  {title:'视频剪辑工具的交互决定',source:'影像制作 · 43 个镜头 · 示例',words:'视频 剪辑 电影 阿狸 字幕',detail:'把镜头顺序和时长变成可以拖动调整的时间线。这里是设计样例，不是从你的真实历史读取的证据。'},
  {title:'为什么保留原来的文件路径',source:'记忆港 · 产品决定 · 示例',words:'路径 迁移 记忆港 历史',detail:'外盘在线时沿原路径读取；外盘离线时明确提醒，不承诺所有运行时都能继续工作。'},
  {title:'一次容量测试留下的记录',source:'研发记录 · 测试方法 · 示例',words:'研发 容量 拍板 测试',detail:'把测试源码、模拟状态与真实生产数据分开。测试完成不等于已经验证线上容量。'},
];
function navigate(page){
  document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==page);
  document.querySelectorAll('nav button').forEach(el=>el.dataset.page===page?el.setAttribute('aria-current','page'):el.removeAttribute('aria-current'));
  history.replaceState(null,'',`#${page}`);
}
document.querySelectorAll('[data-page]').forEach(el=>el.onclick=event=>{event.preventDefault();navigate(el.dataset.page)});
$('.brand').onclick=event=>{event.preventDefault();navigate('harbor')};
function sheet(content){$('#sheetContent').innerHTML=content;$('#sheet').showModal()}
$('#closeSheet').onclick=()=>$('#sheet').close();
$('#sheet').addEventListener('click',event=>{if(event.target===$('#sheet')){const r=$('#sheet').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('#sheet').close()}});
function results(query=''){
  const q=query.trim().toLowerCase();const rows=examples.filter(row=>!q||`${row.title} ${row.words}`.includes(q));$('#results').replaceChildren();$('#empty').hidden=!!rows.length;
  rows.forEach(row=>{const button=document.createElement('button');button.className='result';button.innerHTML=`<span>⌁</span><span><b>${row.title}</b><small>${row.source}</small></span><em>↗</em>`;button.onclick=()=>sheet(`<span class="eyebrow">示例线索</span><h2>${row.title}</h2><p>${row.detail}</p><details><summary>出处与能力边界</summary><p>设计原型使用固定样例，没有读取任务、完整对话或私人记忆。正式版应显示真实出处，并区分证据可读与任务可继续。</p></details>`);$('#results').append(button)})
}
$('#searchForm').onsubmit=event=>{event.preventDefault();results($('#query').value)};results();
const checks=[...document.querySelectorAll('[data-size]')];
function selection(){const picked=checks.filter(el=>el.checked);const total=picked.reduce((sum,el)=>sum+Number(el.dataset.size),0);$('#selection').textContent=`${total.toFixed(1)} GB`;$('#review').disabled=!picked.length||!connected;$('#selectAll').textContent=picked.length===checks.length?'取消全选':'全选建议';return total}
checks.forEach(el=>el.onchange=selection);$('#selectAll').onclick=()=>{const select=checks.some(el=>!el.checked);checks.forEach(el=>el.checked=select);selection()};
$('#review').onclick=()=>{const total=selection();sheet(`<span class="eyebrow">确认方案 · 示例</span><h2>停泊 ${total.toFixed(1)} GB 到外置盘</h2><p>复制 → 校验 → 保留原路径 → 独立复核。全部通过后才移除本机实体。</p><p>外盘断开时，这些内容暂时不可读。当前代码与运行环境不移动。</p><button class="primary" id="demoComplete">演示完成界面（不迁移）</button>`);$('#demoComplete').onclick=()=>{$('#sheet').close();scenario('complete',total)}};
$('#proof').onclick=()=>sheet('<span class="eyebrow">检查范围 · 示例</span><h2>看得到，不等于验证过。</h2><p>首页应说明检查时间、范围与结果，不能因为外盘在线，就声称所有记忆完整或所有任务可以继续。</p><details><summary>查看详细边界</summary><p>文件存在、校验一致、原路径可读、原任务能打开和研发能继续，是五项不同的验证。完成的范围才可以显示为通过。</p></details>');
$('#settings').onclick=()=>sheet('<span class="eyebrow">设备与设置 · 示例</span><h2>存储位置</h2><p>Alex’s Disk · 已连接</p><p>长期保留的项目在列表中标星；不再要求输入路径。断开设备会提示离线，不自动搬动内容。</p><details><summary>更多信息</summary><p>验证记录、原路径、存储设备身份与恢复入口放在这里。云存储仍为未来功能。</p></details>');
$('#theme').onclick=()=>{const light=document.body.classList.toggle('light');$('#theme').textContent=light?'深色':'浅色'};
function desktop(on){$('#app').hidden=on;$('#desktopStage').hidden=!on;$('#desktop').setAttribute('aria-pressed',String(on));$('#desktop').textContent=on?'完整窗口':'桌面卡片'}
$('#desktop').onclick=()=>desktop($('#desktop').getAttribute('aria-pressed')!=='true');$('#openApp').onclick=()=>{desktop(false);navigate('harbor')};
function scenario(name,size=6.3){
  if(name==='offline'||name==='online'){const online=name==='online';connected=online;$('#connection').textContent=online?'外置盘已连接':'外置盘未连接';document.querySelectorAll('.dot,.status i').forEach(el=>el.style.background=online?'#76d3bb':'#e8c090');$('#cardStatus').textContent=online?'外置盘已连接':'外置盘未连接';$('#cardNote').textContent=online?'有 26.4 GB 可以查看停泊方案':'连接外盘后可读取已停泊内容';$('#harbor .primary').disabled=!online;selection();return}
  const stopped=name==='stopped',retained=name==='retained';sheet(`<div class="done-icon">${stopped?'!':'✓'}</div><span class="eyebrow">状态预览 · 不操作真实文件</span><h2>${stopped?'操作已安全停止':'停泊完成'}</h2><p>${stopped?'部分对象尚未通过校验，未完成的内容留在本机。':retained?`已验证 ${size.toFixed(1)} GB，本地副本已保留。此次没有移除本机文件。`:`已验证 ${size.toFixed(1)} GB，本地文件已移除。外盘在线时原路径可读。`}</p><div class="completion ${stopped?'stopped':''}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${stopped?62:100}"><i></i></div><div class="dialog-meta"><span>${stopped?'9 / 11':'5836 / 5836'} 项</span><span>${stopped?'已完成部分保留':'100%'}</span></div><details><summary>查看处理详情</summary><p>耗时与阶段校验记录放在这里。按文件字节统计的移除量不等于系统净增的可用空间；完成迁移不代表全部连续性测试通过。</p></details><button class="primary" id="done">${stopped?'查看已完成部分':'完成'}</button>`);$('#done').onclick=()=>$('#sheet').close()
}
document.querySelectorAll('[data-scenario]').forEach(el=>el.onclick=()=>scenario(el.dataset.scenario));
document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();if($('#sheet').open)$('#sheet').close();desktop(false);navigate('recall');$('#query').focus()}});
navigate(['harbor','recall','dock'].includes(location.hash.slice(1))?location.hash.slice(1):'harbor');
