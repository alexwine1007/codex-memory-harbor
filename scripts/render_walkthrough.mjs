// A captioned slideshow from observed disposable UI states, not a continuous screen recording.
// Requires ffmpeg and development-only sharp. App/trial has no dependency on either.
// node scripts/render_walkthrough.mjs [/absolute/node_modules/with/sharp]
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(import.meta.url);
const sharp=require(require.resolve('sharp',{paths:process.argv[2]?[process.argv[2]]:[root]}));
const output=path.join(root,'docs/launch'),frames=path.join(output,'frames');
await fs.mkdir(frames,{recursive:true});
const strings={
 en:{titles:['Reclaim space. Keep your history.','1 · Inspect before moving anything','2 · Review the exact plan','3 · Copies verified, local rollback kept','4 · Restore when you need it','Try it without touching private history.'],
     notes:['macOS source beta · no telemetry','Old child tasks + cold media; active work stays local','Keep local copies on a new machine or drive','Original-path sample reads independently checked','Sample restore checked; external copies remain','python3 scripts/try_harbor.py  ·  GitHub / alexwine1007 / codex-memory-harbor'],
     disclosure:'Disposable UI fixture · simulated drive identity/capacity · edited steps, not transfer-time footage'},
 'zh-CN':{titles:['给当下腾空间。把过去留得住。','1 · 先盘点，不急着移动','2 · 看清方案，再确认','3 · 校验完成，本地副本仍保留','4 · 需要时，恢复到本机','先用小样例试，不碰私人历史。'],
     notes:['macOS 源码测试版 · 不上传历史，不做遥测','旧子任务与冷素材按需选择；活跃工作留在本机','新机器、新介质，先保留本地副本','已独立检查样例沿原路径可读','样例恢复已核查；外部副本保留','python3 scripts/try_harbor.py  ·  GitHub / alexwine1007 / codex-memory-harbor'],
     disclosure:'隔离测试界面 · 盘身份/容量为模拟值 · 步骤截图剪辑，非传输耗时录屏'}
};
const escape=text=>text.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
for(const [language,t] of Object.entries(strings)){
 for(let i=0;i<6;i++){
  let content;
  if(i===0||i===5){
   const image=await fs.readFile(path.join(output,`social-preview.${language}.png`));
   content=`<image x="55" y="105" width="1170" height="555" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,${image.toString('base64')}"/>`;
  }else{
   const phase=['inventory','plan','complete','restore'][i-1];
   const image=await fs.readFile(path.join(output,'captures',`${phase}.${language}.jpg`));
   content=`<image x="55" y="93" width="1170" height="555" preserveAspectRatio="xMidYMid meet" href="data:image/jpeg;base64,${image.toString('base64')}"/>`;
  }
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#101421"/><g font-family="-apple-system, 'PingFang SC', 'Helvetica Neue', sans-serif"><text x="55" y="43" font-size="30" font-weight="700" fill="#faf9ff">${escape(t.titles[i])}</text><text x="55" y="76" font-size="19" fill="#bbbace">${escape(t.notes[i])}</text></g>${content}<text x="55" y="690" font-family="-apple-system, 'PingFang SC', sans-serif" font-size="17" fill="#a6a3bd">${escape(t.disclosure)}</text></svg>`;
  await sharp(Buffer.from(svg)).png().toFile(path.join(frames,`${language}-${String(i).padStart(2,'0')}.png`));
 }
 execFileSync('ffmpeg',['-y','-loglevel','error','-framerate','1/5','-i',path.join(frames,`${language}-%02d.png`),'-t','30','-r','15','-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',path.join(output,`walkthrough.${language}.mp4`)],{stdio:'inherit'});
}
console.log('Rendered two 30-second silent, captioned fixture walkthroughs.');
