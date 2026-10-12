// Code-native brand composition. Rasterizes the existing shared vector, no image retouching.
// node scripts/render_launch.mjs [/absolute/node_modules/with/sharp]
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(import.meta.url);
const sharp=require(require.resolve('sharp',{paths:process.argv[2]?[process.argv[2]]:[root]}));
const directory=path.join(root,'docs/launch');
const mark=await fs.readFile(path.join(root,'skills/codex-memory-harbor/assets/dashboard/brand-mark.svg'),'utf8');
const nested=mark.replace('<svg ', '<svg x="948" y="196" width="238" height="238" ');
const text={en:{eyebrow:'MEMORY HARBOR',a:'Reclaim space.',b:'Keep your history.',description:'Verified copies. Original paths.',detail:'Old Codex child-task logs + cold media → external drive',footer:'macOS · MIT · Local-first',beta:'SOURCE BETA · DRIVE REQUIRED'},
 'zh-CN':{eyebrow:'MEMORY HARBOR · 记忆港',a:'给当下腾空间。',b:'把过去留得住。',description:'逐个校验，沿原路径读取。',detail:'Codex 旧子任务与冷素材 → 外置硬盘',footer:'macOS · MIT 开源 · 本地优先',beta:'源码测试版 · 外盘在线时可读'}};
for(const [language,t] of Object.entries(text)){
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640" role="img" aria-label="Memory Harbor">
 <defs><radialGradient id="ambient"><stop stop-color="#32346c" stop-opacity=".65"/><stop offset="1" stop-color="#101421" stop-opacity="0"/></radialGradient><linearGradient id="line"><stop stop-color="#936cff"/><stop offset="1" stop-color="#12cfda"/></linearGradient></defs>
 <rect width="1280" height="640" fill="#101421"/><ellipse cx="1070" cy="275" rx="370" ry="375" fill="url(#ambient)"/>
 <g font-family="-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', sans-serif">
 <text x="72" y="95" font-size="27" font-weight="600" letter-spacing="2" fill="#e3e1fa">${t.eyebrow}</text>
 <rect x="72" y="130" width="46" height="4" rx="2" fill="url(#line)"/>
 <text x="68" y="266" font-size="${language==='en'?70:67}" font-weight="700" letter-spacing="-2" fill="#faf9ff">${t.a}</text>
 <text x="68" y="351" font-size="${language==='en'?70:67}" font-weight="700" letter-spacing="-2" fill="#faf9ff">${t.b}</text>
 <text x="72" y="423" font-size="29" fill="#cac7e0">${t.description}</text>
 <text x="72" y="466" font-size="21" fill="#9294ad">${t.detail}</text>
 <path d="M72 545H1208" stroke="#8186a1" stroke-opacity=".25"/>
 <text x="72" y="589" font-size="20" fill="#bbbace">${t.footer}</text>
 <text x="1208" y="589" text-anchor="end" font-size="16" fill="#9294ad">${t.beta}</text>
 </g>${nested}</svg>`;
 await fs.writeFile(path.join(directory,`social-preview.${language}.svg`),svg);
 await sharp(Buffer.from(svg)).png().toFile(path.join(directory,`social-preview.${language}.png`));
}
console.log('Rendered bilingual 1280×640 covers from the shared vector.');
