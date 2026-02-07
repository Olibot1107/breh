import http from "node:http";

const PORT = process.env.PORT ? Number(process.env.PORT) : 3000;

let termWidth = process.stdout.columns || 80;
let termHeight = process.stdout.rows || 24;

const WHITE = { r: 255, g: 255, b: 255 };
const DEFAULT_BG = { r: 0, g: 0, b: 0 };
let backgroundColor = { ...DEFAULT_BG };

// 2x2 subpixel buffer (double width & height)
let subWidth = termWidth * 2;
let subHeight = termHeight * 2;
let subBuffer = [];

const QUAD_CHARS = [
  " ", // 0
  "▘", // 1 TL
  "▝", // 2 TR
  "▀", // 3 TL+TR
  "▖", // 4 BL
  "▌", // 5 TL+BL
  "▞", // 6 TR+BL
  "▛", // 7 TL+TR+BL
  "▗", // 8 BR
  "▚", // 9 TL+BR
  "▐", // 10 TR+BR
  "▜", // 11 TL+TR+BR
  "▄", // 12 BL+BR
  "▙", // 13 TL+BL+BR
  "▟", // 14 TR+BL+BR
  "■"  // 15 all (solid square)
];

function ansi(cmd) {
  process.stdout.write(cmd);
}

function hideCursor() {
  ansi("\x1b[?25l");
}

function showCursor() {
  ansi("\x1b[?25h");
}

function clearToWhite() {
  ansi(`\x1b[48;2;${backgroundColor.r};${backgroundColor.g};${backgroundColor.b}m\x1b[2J\x1b[H\x1b[0m`);
}

function initBuffers() {
  termWidth = process.stdout.columns || termWidth;
  termHeight = process.stdout.rows || termHeight;
  subWidth = termWidth * 2;
  subHeight = termHeight * 2;
  subBuffer = Array.from({ length: subHeight }, () =>
    Array.from({ length: subWidth }, () => ({ ...WHITE }))
  );
}

function toYuv(c) {
  // BT.601 luma/chroma
  const y = 0.299 * c.r + 0.587 * c.g + 0.114 * c.b;
  const u = -0.168736 * c.r - 0.331264 * c.g + 0.5 * c.b;
  const v = 0.5 * c.r - 0.418688 * c.g - 0.081312 * c.b;
  return { y, u, v };
}

function colorDist2(a, b) {
  // Perceptual-ish distance in YUV
  const ya = toYuv(a);
  const yb = toYuv(b);
  const dy = ya.y - yb.y;
  const du = ya.u - yb.u;
  const dv = ya.v - yb.v;
  return dy * dy * 2.0 + du * du + dv * dv;
}

function averageColor(colors) {
  let r = 0, g = 0, b = 0;
  for (const c of colors) {
    r += c.r; g += c.g; b += c.b;
  }
  const n = colors.length || 1;
  return { r: Math.round(r / n), g: Math.round(g / n), b: Math.round(b / n) };
}

function pickTwoColors(quads) {
  // 2-means (k=2) for 4 pixels. Better separation than farthest-pair.
  let c1 = quads[0];
  let c2 = quads[quads.length - 1];
  // If all nearly identical, fall back to single color.
  let maxD = 0;
  for (let i = 0; i < quads.length; i++) {
    for (let j = i + 1; j < quads.length; j++) {
      maxD = Math.max(maxD, colorDist2(quads[i], quads[j]));
    }
  }
  if (maxD < 64) {
    const avg = averageColor(quads);
    return { fg: avg, bg: avg, maskBits: [1, 1, 1, 1] };
  }

  for (let iter = 0; iter < 3; iter++) {
    const g1 = [];
    const g2 = [];
    for (const q of quads) {
      const d1 = colorDist2(q, c1);
      const d2 = colorDist2(q, c2);
      if (d1 <= d2) g1.push(q);
      else g2.push(q);
    }
    c1 = averageColor(g1.length ? g1 : quads);
    c2 = averageColor(g2.length ? g2 : quads);
  }

  const fgSet = [];
  const bgSet = [];
  const maskBits = [];
  for (const q of quads) {
    const d1 = colorDist2(q, c1);
    const d2 = colorDist2(q, c2);
    if (d1 <= d2) {
      fgSet.push(q);
      maskBits.push(1);
    } else {
      bgSet.push(q);
      maskBits.push(0);
    }
  }

  const fg = averageColor(fgSet.length ? fgSet : quads);
  const bg = averageColor(bgSet.length ? bgSet : quads);
  return { fg, bg, maskBits };
}

function drawCell(cellX, cellY) {
  const x0 = cellX * 2;
  const y0 = cellY * 2;

  const TL = subBuffer[y0][x0];
  const TR = subBuffer[y0][x0 + 1];
  const BL = subBuffer[y0 + 1][x0];
  const BR = subBuffer[y0 + 1][x0 + 1];

  const quads = [TL, TR, BL, BR];
  const { fg, bg, maskBits } = pickTwoColors(quads);

  // Build quadrant mask (TL=1, TR=2, BL=4, BR=8)
  let mask = 0;
  if (maskBits[0]) mask |= 1;
  if (maskBits[1]) mask |= 2;
  if (maskBits[2]) mask |= 4;
  if (maskBits[3]) mask |= 8;

  const ch = QUAD_CHARS[mask];
  const row = cellY + 1;
  const col = cellX + 1;

  const bgColor = mask === 0 ? backgroundColor : bg;

  ansi(
    `\x1b[${row};${col}H` +
      `\x1b[38;2;${fg.r};${fg.g};${fg.b}m` +
      `\x1b[48;2;${bgColor.r};${bgColor.g};${bgColor.b}m` +
      `${ch}\x1b[0m`
  );
}

function setPixel(x, y, r, g, b) {
  if (x < 0 || y < 0 || x >= subWidth || y >= subHeight) return;
  subBuffer[y][x] = { r, g, b };
  const cellX = Math.floor(x / 2);
  const cellY = Math.floor(y / 2);
  drawCell(cellX, cellY);
}

function resetTerminal() {
  showCursor();
  ansi("\x1b[0m\x1b[2J\x1b[H");
}

process.stdout.on("resize", () => {
  initBuffers();
  clearToWhite();
});

process.on("SIGINT", () => {
  resetTerminal();
  process.exit(0);
});

process.on("SIGTERM", () => {
  resetTerminal();
  process.exit(0);
});

hideCursor();
initBuffers();
clearToWhite();

const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Terminal Pixel Control</title>
    <style>
      :root { --bg:#0f1015; --panel:#171923; --text:#e8e8e8; --accent:#6ee7ff; }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: radial-gradient(1200px 800px at 20% 10%, #1c2433, #0f1015 60%);
        color: var(--text);
        font: 16px/1.4 "Space Grotesk", system-ui, sans-serif;
        display: grid; place-items: center; min-height: 100vh;
      }
      .wrap { width: min(960px, 94vw); display: grid; gap: 16px; }
      .panel {
        background: color-mix(in oklab, var(--panel), #000 10%);
        border: 1px solid #2a3142;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.35);
      }
      .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
      .label { opacity: 0.8; }
      button {
        background: var(--accent);
        color: #0b0f14; border: 0; padding: 10px 14px;
        border-radius: 10px; font-weight: 600; cursor: pointer;
      }
      input[type="color"] { width: 44px; height: 36px; border: none; background: transparent; }
      canvas {
        width: 100%; height: auto; image-rendering: pixelated;
        background: #fff; border-radius: 8px; border: 1px solid #2a3142;
      }
      .hint { opacity: 0.7; font-size: 13px; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="panel">
        <div class="row">
          <div class="label">Color</div>
          <input id="color" type="color" value="#ff0000" />
          <button id="clear">Clear (White)</button>
          <div class="hint">Click or drag on the canvas to set terminal subpixels.</div>
        </div>
      </div>
      <div class="panel">
        <canvas id="canvas"></canvas>
      </div>
    </div>

    <script>
      const canvas = document.getElementById('canvas');
      const ctx = canvas.getContext('2d');
      const colorInput = document.getElementById('color');
      const clearBtn = document.getElementById('clear');

      let grid = { width: 0, height: 0 };

      async function fetchSize() {
        const res = await fetch('/size');
        grid = await res.json();
        canvas.width = grid.width;
        canvas.height = grid.height;
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }

      function hexToRgb(hex) {
        const val = hex.replace('#', '');
        const r = parseInt(val.slice(0, 2), 16);
        const g = parseInt(val.slice(2, 4), 16);
        const b = parseInt(val.slice(4, 6), 16);
        return { r, g, b };
      }

      async function sendPixel(x, y) {
        const { r, g, b } = hexToRgb(colorInput.value);
        await fetch('/pixel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ x, y, r, g, b })
        });
        ctx.fillStyle = colorInput.value;
        ctx.fillRect(x, y, 1, 1);
      }

      let painting = false;

      function getPos(evt) {
        const rect = canvas.getBoundingClientRect();
        const x = Math.floor((evt.clientX - rect.left) * (canvas.width / rect.width));
        const y = Math.floor((evt.clientY - rect.top) * (canvas.height / rect.height));
        return { x, y };
      }

      canvas.addEventListener('mousedown', (e) => {
        painting = true;
        const { x, y } = getPos(e);
        sendPixel(x, y);
      });

      canvas.addEventListener('mousemove', (e) => {
        if (!painting) return;
        const { x, y } = getPos(e);
        sendPixel(x, y);
      });

      window.addEventListener('mouseup', () => { painting = false; });

      clearBtn.addEventListener('click', async () => {
        await fetch('/clear', { method: 'POST' });
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      });

      fetchSize();
      window.addEventListener('resize', fetchSize);
    </script>
  </body>
</html>`;

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (req.method === "GET" && req.url === "/size") {
      initBuffers();
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ width: subWidth, height: subHeight, subpixel: "2x2" }));
      return;
    }

    if (req.method === "POST" && req.url === "/clear") {
      initBuffers();
      clearToWhite();
      res.writeHead(204);
      res.end();
      return;
    }

    if (req.method === "POST" && req.url === "/background") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        try {
          const data = JSON.parse(body || "{}");
          const r = Math.max(0, Math.min(255, Number(data.r)));
          const g = Math.max(0, Math.min(255, Number(data.g)));
          const b = Math.max(0, Math.min(255, Number(data.b)));
          backgroundColor = { r, g, b };
          clearToWhite();
          res.writeHead(204);
          res.end();
        } catch {
          res.writeHead(400);
          res.end("Bad JSON");
        }
      });
      return;
    }

    if (req.method === "POST" && req.url === "/pixel") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        try {
          const data = JSON.parse(body || "{}");
          const x = Number(data.x);
          const y = Number(data.y);
          const r = Math.max(0, Math.min(255, Number(data.r)));
          const g = Math.max(0, Math.min(255, Number(data.g)));
          const b = Math.max(0, Math.min(255, Number(data.b)));
          if (Number.isFinite(x) && Number.isFinite(y)) {
            setPixel(Math.floor(x), Math.floor(y), r, g, b);
          }
          res.writeHead(204);
          res.end();
        } catch {
          res.writeHead(400);
          res.end("Bad JSON");
        }
      });
      return;
    }

    if (req.method === "POST" && req.url === "/draw") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        try {
          const data = JSON.parse(body || "{}");
          const pixels = Array.isArray(data.pixels) ? data.pixels : [];
          for (const p of pixels) {
            const x = Number(p.x);
            const y = Number(p.y);
            const r = Math.max(0, Math.min(255, Number(p.r)));
            const g = Math.max(0, Math.min(255, Number(p.g)));
            const b = Math.max(0, Math.min(255, Number(p.b)));
            if (Number.isFinite(x) && Number.isFinite(y)) {
              setPixel(Math.floor(x), Math.floor(y), r, g, b);
            }
          }
          res.writeHead(204);
          res.end();
        } catch {
          res.writeHead(400);
          res.end("Bad JSON");
        }
      });
      return;
    }

    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("Not found");
  } catch (err) {
    res.writeHead(500, { "Content-Type": "text/plain" });
    res.end("Server error");
  }
});

server.listen(PORT, () => {
  process.stderr.write(`Server running on http://localhost:${PORT}\n`);
});
