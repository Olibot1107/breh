const fs = require('fs');
const path = require('path');
const { createCanvas, loadImage } = require('canvas');
const Display = require('./e.cjs');

const W = 160;
const H = 96;
const FPS = 30;

const d = new Display(W, H);

const framesDir = './frames';
const frames = fs
  .readdirSync(framesDir)
  .filter(f => f.endsWith('.png'))
  .sort();

const canvas = createCanvas(W, H);
const ctx = canvas.getContext('2d');

let i = 0;

async function playFrame() {
  if (i >= frames.length) i = 0;

  const img = await loadImage(path.join(framesDir, frames[i]));
  ctx.drawImage(img, 0, 0, W, H);

  const data = ctx.getImageData(0, 0, W, H).data;

  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const idx = (y * W + x) * 4;
      d.setPixel(
        x,
        y,
        data[idx],
        data[idx + 1],
        data[idx + 2]
      );
    }
  }

  d.draw();
  i++;
}

setInterval(() => {
  playFrame().catch(console.error);
}, 1000 / FPS);
