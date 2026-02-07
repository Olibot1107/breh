// term-display.js — OPTIMIZED BLOCK MODE RENDERER

const BLOCK_CHARS = [
  ' ','🬀','🬁','🬆','🬂','🬇','🬋','🬕','🬃','🬈','🬌','🬖','🬏','🬙','🬟','🬩',
  '🬄','🬉','🬍','🬗','🬐','🬚','🬠','🬪','🬒','🬜','🬢','🬬','🬥','🬯','🬲','🬸',
  '🬅','🬊','🬎','🬘','🬑','🬛','🬡','🬫','🬓','🬝','🬣','🬭','🬦','🬰','🬳','🬹',
  '🬔','🬞','🬤','🬮','🬧','🬱','🬴','🬺','🬨','🬵','🬶','🬻','🬷','🬼','🬽','█'
];

class TermDisplay {
  constructor(width, height) {
    this.width = width;
    this.height = height;

    // 2x3 block characters
    this.cellW = Math.ceil(width / 2);
    this.cellH = Math.ceil(height / 3);

    // Flat arrays for speed
    const size = width * height;
    this.r = new Uint8Array(size);
    this.g = new Uint8Array(size);
    this.b = new Uint8Array(size);

    process.stdout.write('\x1b[2J\x1b[H\x1b[?25l');
    process.on('exit', () => {
      process.stdout.write('\x1b[?25h\x1b[0m\n');
    });
  }

  clear(r = 0, g = 0, b = 0) {
    this.r.fill(r);
    this.g.fill(g);
    this.b.fill(b);
  }

  setPixel(x, y, r, g, b) {
    x = x | 0;
    y = y | 0;
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return;
    
    const i = y * this.width + x;
    this.r[i] = r;
    this.g[i] = g;
    this.b[i] = b;
  }

  draw() {
    let out = '\x1b[H';
    let lastFg = '', lastBg = '';

    for (let cy = 0; cy < this.cellH; cy++) {
      for (let cx = 0; cx < this.cellW; cx++) {
        let mask = 0;
        let fgR = 0, fgG = 0, fgB = 0, fgN = 0;
        let bgR = 0, bgG = 0, bgB = 0, bgN = 0;

        // Check 6 pixels in 2x3 grid
        for (let py = 0; py < 3; py++) {
          for (let px = 0; px < 2; px++) {
            const x = cx * 2 + px;
            const y = cy * 3 + py;
            if (x >= this.width || y >= this.height) continue;

            const i = y * this.width + x;
            const pr = this.r[i];
            const pg = this.g[i];
            const pb = this.b[i];
            const brightness = pr + pg + pb;

            const bit = py * 2 + px;
            
            if (brightness > 30) {
              mask |= (1 << bit);
              fgR += pr; fgG += pg; fgB += pb; fgN++;
            } else if (brightness > 0) {
              bgR += pr; bgG += pg; bgB += pb; bgN++;
            }
          }
        }

        // Render cell
        if (mask === 0) {
          // No foreground pixels
          if (bgN > 0) {
            const bg = `\x1b[48;2;${bgR/bgN|0};${bgG/bgN|0};${bgB/bgN|0}m`;
            if (bg !== lastBg) { out += bg; lastBg = bg; }
            out += ' ';
          } else {
            if (lastBg || lastFg) {
              out += '\x1b[0m';
              lastBg = lastFg = '';
            }
            out += ' ';
          }
        } else {
          // Has foreground pixels
          const fg = `\x1b[38;2;${fgR/fgN|0};${fgG/fgN|0};${fgB/fgN|0}m`;
          if (fg !== lastFg) { out += fg; lastFg = fg; }

          if (bgN > 0 && mask !== 63) {
            const bg = `\x1b[48;2;${bgR/bgN|0};${bgG/bgN|0};${bgB/bgN|0}m`;
            if (bg !== lastBg) { out += bg; lastBg = bg; }
          } else if (lastBg) {
            out += '\x1b[49m';
            lastBg = '';
          }

          out += BLOCK_CHARS[mask];
        }
      }
      out += '\x1b[0m\n';
      lastFg = lastBg = '';
    }

    process.stdout.write(out);
  }

  drawLine(x0, y0, x1, y1, r, g, b) {
    const dx = Math.abs(x1 - x0);
    const dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let err = dx - dy;

    while (true) {
      this.setPixel(x0, y0, r, g, b);
      if (Math.abs(x0 - x1) < 1 && Math.abs(y0 - y1) < 1) break;

      const e2 = err * 2;
      if (e2 > -dy) { err -= dy; x0 += sx; }
      if (e2 < dx) { err += dx; y0 += sy; }
    }
  }

  fillRect(x, y, w, h, r, g, b) {
    const x0 = x | 0;
    const y0 = y | 0;
    const x1 = Math.min(this.width, x + w | 0);
    const y1 = Math.min(this.height, y + h | 0);

    for (let py = y0; py < y1; py++) {
      const row = py * this.width;
      for (let px = x0; px < x1; px++) {
        const i = row + px;
        this.r[i] = r;
        this.g[i] = g;
        this.b[i] = b;
      }
    }
  }

  drawCircle(cx, cy, radius, r, g, b, filled = false) {
    const minX = Math.max(0, cx - radius - 1 | 0);
    const maxX = Math.min(this.width, cx + radius + 2 | 0);
    const minY = Math.max(0, cy - radius - 1 | 0);
    const maxY = Math.min(this.height, cy + radius + 2 | 0);

    for (let y = minY; y < maxY; y++) {
      const dy = y - cy;
      for (let x = minX; x < maxX; x++) {
        const dx = x - cx;
        const d = Math.sqrt(dx * dx + dy * dy);
        
        if (filled) {
          if (d <= radius) this.setPixel(x, y, r, g, b);
        } else {
          if (Math.abs(d - radius) < 1) this.setPixel(x, y, r, g, b);
        }
      }
    }
  }
}

module.exports = TermDisplay;