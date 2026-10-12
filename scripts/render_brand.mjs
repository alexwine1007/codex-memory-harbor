// Deterministically rasterize our editable vector for the macOS icon. No AI/raster retouching.
// Usage: node scripts/render_brand.mjs [absolute node_modules directory containing sharp]
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(import.meta.url);
const sharp=require(require.resolve('sharp',{paths:process.argv[2]?[process.argv[2]]:[root]}));
await sharp(path.join(root,'skills/codex-memory-harbor/assets/dashboard/brand-mark.svg'),{density:288})
  .resize(1024,1024).png().toFile(path.join(root,'skills/codex-memory-harbor/assets/memory-harbor-logo-v5-1024.png'));
