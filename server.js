import http from "node:http";
import { WebSocketServer } from "ws";

const PORT = process.env.PORT ? Number(process.env.PORT) : 3000;

let termWidth = process.stdout.columns || 80;
let termHeight = process.stdout.rows || 24;

const DEFAULT_BG = { r: 0, g: 0, b: 0 };
let backgroundColor = { ...DEFAULT_BG };

function ansi(cmd) {
  process.stdout.write(cmd);
}

function hideCursor() {
  ansi("\x1b[?25l");
}

function showCursor() {
  ansi("\x1b[?25h");
}

function clearScreen() {
  ansi(`\x1b[48;2;${backgroundColor.r};${backgroundColor.g};${backgroundColor.b}m\x1b[2J\x1b[H\x1b[0m`);
}

function refreshSize() {
  termWidth = process.stdout.columns || termWidth;
  termHeight = process.stdout.rows || termHeight;
}

function resetTerminal() {
  showCursor();
  ansi("\x1b[0m\x1b[2J\x1b[H");
}

process.stdout.on("resize", () => {
  refreshSize();
  clearScreen();
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
refreshSize();
clearScreen();

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
          <button id="clear">Clear</button>
          <div class="hint">Click or drag to draw (client chooses chars/colors).</div>
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

      let socket = null;
      let socketReady = false;
      let pending = [];
      let flushId = null;

      function connectSocket() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        socket = new WebSocket(proto + '://' + location.host);
        socketReady = false;
        socket.addEventListener('open', () => { socketReady = true; });
        socket.addEventListener('close', () => {
          socketReady = false;
          setTimeout(connectSocket, 500);
        });
      }

      function scheduleFlush() {
        if (flushId !== null) return;
        flushId = requestAnimationFrame(() => {
          flushId = null;
          if (!socketReady || pending.length === 0) return;
          const batch = pending;
          pending = [];
          socket.send(JSON.stringify({ type: 'cells', cells: batch }));
        });
      }

      function sendCell(x, y) {
        const { r, g, b } = hexToRgb(colorInput.value);
        pending.push({ x, y, ch: '■', fg: [r,g,b], bg: [0,0,0] });
        scheduleFlush();
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
        sendCell(x, y);
      });

      canvas.addEventListener('mousemove', (e) => {
        if (!painting) return;
        const { x, y } = getPos(e);
        sendCell(x, y);
      });

      window.addEventListener('mouseup', () => { painting = false; });

      clearBtn.addEventListener('click', async () => {
        if (socketReady) {
          socket.send(JSON.stringify({ type: 'clear' }));
        } else {
          await fetch('/clear', { method: 'POST' });
        }
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      });

      fetchSize();
      window.addEventListener('resize', fetchSize);
      connectSocket();
    </script>
  </body>
</html>`;

function parseColorArr(arr) {
  if (!Array.isArray(arr) || arr.length < 3) return null;
  const r = Math.max(0, Math.min(255, Number(arr[0])));
  const g = Math.max(0, Math.min(255, Number(arr[1])));
  const b = Math.max(0, Math.min(255, Number(arr[2])));
  if (!Number.isFinite(r) || !Number.isFinite(g) || !Number.isFinite(b)) return null;
  return { r, g, b };
}

function formatDrawCell(x, y, ch, fg, bg, state) {
  if (x < 0 || y < 0 || x >= termWidth || y >= termHeight) return "";
  const row = y + 1;
  const col = x + 1;
  const fgColor = fg || { r: 255, g: 255, b: 255 };
  const bgColor = bg || backgroundColor;
  const safeCh = typeof ch === "string" && ch.length ? ch[0] : " ";

  let out = "";
  out += `\x1b[${row};${col}H`;

  if (!state || state.fg !== fgColor) {
    out += `\x1b[38;2;${fgColor.r};${fgColor.g};${fgColor.b}m`;
  }
  if (!state || state.bg !== bgColor) {
    out += `\x1b[48;2;${bgColor.r};${bgColor.g};${bgColor.b}m`;
  }

  out += safeCh;
  if (state) {
    state.fg = fgColor;
    state.bg = bgColor;
  }
  return out;
}

function drawCells(cells) {
  const state = { fg: null, bg: null };
  let out = "";
  for (const c of cells) {
    const x = Number(c.x);
    const y = Number(c.y);
    const ch = c.ch;
    const fg = parseColorArr(c.fg);
    const bg = parseColorArr(c.bg);
    if (Number.isFinite(x) && Number.isFinite(y)) {
      out += formatDrawCell(Math.floor(x), Math.floor(y), ch, fg, bg, state);
    }
  }
  if (out) ansi(out + "\x1b[0m");
}

function drawFrame(rows) {
  let out = "";
  for (let y = 0; y < rows.length && y < termHeight; y++) {
    const row = rows[y];
    if (!row || !Array.isArray(row.runs)) continue;
    out += `\x1b[${y + 1};1H`;
    for (const run of row.runs) {
      const fg = parseColorArr(run.fg) || { r: 255, g: 255, b: 255 };
      const bg = parseColorArr(run.bg) || backgroundColor;
      const ch = typeof run.ch === "string" && run.ch.length ? run.ch[0] : " ";
      const count = Math.max(0, Math.min(termWidth, Number(run.count) || 0));
      out += `\x1b[38;2;${fg.r};${fg.g};${fg.b}m`;
      out += `\x1b[48;2;${bg.r};${bg.g};${bg.b}m`;
      out += ch.repeat(count);
    }
  }
  if (out) ansi(out + "\x1b[0m");
}

function parseJsonMessage(data) {
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (req.method === "GET" && req.url === "/size") {
      refreshSize();
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ width: termWidth, height: termHeight }));
      return;
    }

    if (req.method === "POST" && req.url === "/clear") {
      clearScreen();
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
          clearScreen();
          res.writeHead(204);
          res.end();
        } catch {
          res.writeHead(400);
          res.end("Bad JSON");
        }
      });
      return;
    }

    if (req.method === "POST" && req.url === "/cell") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        try {
          const data = JSON.parse(body || "{}");
          const x = Number(data.x);
          const y = Number(data.y);
          const ch = data.ch;
          const fg = parseColorArr(data.fg);
          const bg = parseColorArr(data.bg);
          if (Number.isFinite(x) && Number.isFinite(y)) {
            const out = formatDrawCell(Math.floor(x), Math.floor(y), ch, fg, bg);
            if (out) ansi(out + "\x1b[0m");
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

    if (req.method === "POST" && req.url === "/drawcells") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        try {
          const data = JSON.parse(body || "{}");
          const cells = Array.isArray(data.cells) ? data.cells : [];
          drawCells(cells);
          res.writeHead(204);
          res.end();
        } catch {
          res.writeHead(400);
          res.end("Bad JSON");
        }
      });
      return;
    }

    // Full frame: server expects one row per line; client sends pre-colored runs
    if (req.method === "POST" && req.url === "/frame") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        try {
          const data = JSON.parse(body || "{}");
          const rows = Array.isArray(data.rows) ? data.rows : [];
          drawFrame(rows);
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

const wss = new WebSocketServer({ server });

wss.on("connection", (ws) => {
  ws.on("message", (message) => {
    const data = parseJsonMessage(message.toString());
    if (!data || typeof data.type !== "string") return;

    if (data.type === "clear") {
      clearScreen();
      return;
    }

    if (data.type === "background") {
      const r = Math.max(0, Math.min(255, Number(data.r)));
      const g = Math.max(0, Math.min(255, Number(data.g)));
      const b = Math.max(0, Math.min(255, Number(data.b)));
      if (Number.isFinite(r) && Number.isFinite(g) && Number.isFinite(b)) {
        backgroundColor = { r, g, b };
        clearScreen();
      }
      return;
    }

    if (data.type === "cell") {
      const x = Number(data.x);
      const y = Number(data.y);
      const ch = data.ch;
      const fg = parseColorArr(data.fg);
      const bg = parseColorArr(data.bg);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        const out = formatDrawCell(Math.floor(x), Math.floor(y), ch, fg, bg);
        if (out) ansi(out + "\x1b[0m");
      }
      return;
    }

    if (data.type === "cells") {
      const cells = Array.isArray(data.cells) ? data.cells : [];
      drawCells(cells);
      return;
    }

    if (data.type === "frame") {
      const rows = Array.isArray(data.rows) ? data.rows : [];
      drawFrame(rows);
    }
  });
});
