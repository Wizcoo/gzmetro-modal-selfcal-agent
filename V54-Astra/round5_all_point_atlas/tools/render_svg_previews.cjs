// Offline SVG rasterization only: no browser, UI control, server, or network.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const sharp = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1112-611-0_26.1112.611.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/sharp');
const root = path.resolve(__dirname, '..');
const cases = [
  'left/780638327479/svg/ZXJ6_2026-11-09.svg',
  'left/780630499846/svg/ZJ1_2026-11-06.svg',
  'right/780639298317/svg/YD1102_2026-11-06.svg',
  'left/780637798298/svg/ZD2101_2026-11-07.svg',
];
(async () => {
  fs.mkdirSync(path.join(root, 'previews'), { recursive: true });
  const records = [];
  for (const file of cases) {
    const source = path.join(root, 'plots', file);
    const bytes = fs.readFileSync(source);
    const name = file.replaceAll('/', '_').replace('.svg', '.png');
    const target = path.join(root, 'previews', name);
    const info = await sharp(bytes, { density: 120 }).png().toFile(target);
    records.push({ source: file, sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
      preview: 'previews/' + name, width: info.width, height: info.height });
  }
  fs.writeFileSync(path.join(root, 'reports', 'svg_preview_render.json'), JSON.stringify({
    method: 'Existing generated SVGs rasterized locally with sharp; no redrawing or browser automation', records
  }, null, 2));
  console.log(JSON.stringify(records));
})();
