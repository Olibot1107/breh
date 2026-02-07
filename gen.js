// video-player.js — REAL VIDEO PLAYBACK IN TERMINAL

const fs = require('fs');
const { spawn } = require('child_process');
const { createCanvas, loadImage } = require('canvas');

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
    this.cellW = Math.ceil(width / 2);
    this.cellH = Math.ceil(height / 3);

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

  loadFromImageData(imageData) {
    const data = imageData.data;
    for (let y = 0; y < this.height; y++) {
      for (let x = 0; x < this.width; x++) {
        const i = y * this.width + x;
        const srcIdx = (y * this.width + x) * 4;
        this.r[i] = data[srcIdx];
        this.g[i] = data[srcIdx + 1];
        this.b[i] = data[srcIdx + 2];
      }
    }
  }

  draw() {
    let out = '\x1b[H';
    let lastFg = '', lastBg = '';

    for (let cy = 0; cy < this.cellH; cy++) {
      for (let cx = 0; cx < this.cellW; cx++) {
        let mask = 0;
        let fgR = 0, fgG = 0, fgB = 0, fgN = 0;
        let bgR = 0, bgG = 0, bgB = 0, bgN = 0;

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

        if (mask === 0) {
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
}

// Get video FPS using ffprobe
function getVideoFPS(videoPath) {
  return new Promise((resolve, reject) => {
    const ffprobe = spawn('ffprobe', [
      '-v', 'error',
      '-select_streams', 'v:0',
      '-show_entries', 'stream=r_frame_rate',
      '-of', 'default=noprint_wrappers=1:nokey=1',
      videoPath
    ]);

    let output = '';
    ffprobe.stdout.on('data', (data) => {
      output += data.toString();
    });

    ffprobe.on('close', (code) => {
      if (code !== 0) {
        reject(new Error('Failed to get video FPS'));
        return;
      }
      
      // Parse fraction like "30000/1001" or "30/1"
      const parts = output.trim().split('/');
      const fps = parseInt(parts[0]) / parseInt(parts[1]);
      resolve(fps);
    });
  });
}

// VIDEO PLAYER
async function playVideo(videoPath, targetWidth = 200, targetFPS = null) {
  if (!fs.existsSync(videoPath)) {
    console.error(`ERROR: Video file not found: ${videoPath}`);
    process.exit(1);
  }

  // Get actual video FPS if not specified
  if (!targetFPS) {
    console.log('[INFO] Detecting video FPS...');
    targetFPS = await getVideoFPS(videoPath);
    console.log(`[INFO] Detected FPS: ${targetFPS.toFixed(2)}`);
  }

  // Calculate height maintaining aspect ratio (assume 16:9)
  const targetHeight = Math.floor(targetWidth * 9 / 16);
  
  console.log(`[INFO] Playing: ${videoPath}`);
  console.log(`[INFO] Resolution: ${targetWidth}x${targetHeight} pixels`);
  console.log(`[INFO] Playback FPS: ${targetFPS.toFixed(2)}`);
  console.log('[INFO] Press Ctrl+C to stop\n');

  const display = new TermDisplay(targetWidth, targetHeight);
  const canvas = createCanvas(targetWidth, targetHeight);
  const ctx = canvas.getContext('2d');

  // Start audio playback with ffplay (separate process)
  const audio = spawn('ffplay', [
    '-i', videoPath,
    '-nodisp',      // No video display
    '-autoexit',    // Exit when done
    '-loglevel', 'quiet'
  ], {
    stdio: 'ignore'
  });

  // Extract frames using ffmpeg
  const ffmpeg = spawn('ffmpeg', [
    '-i', videoPath,
    '-vf', `fps=${targetFPS},scale=${targetWidth}:${targetHeight}`,
    '-f', 'image2pipe',
    '-pix_fmt', 'rgb24',
    '-vcodec', 'rawvideo',
    '-'
  ], {
    stdio: ['ignore', 'pipe', 'ignore']
  });

  const frameSize = targetWidth * targetHeight * 3;
  let buffer = Buffer.alloc(0);
  let frameCount = 0;
  const frameDuration = 1000 / targetFPS; // milliseconds per frame
  const startTime = Date.now();

  ffmpeg.stdout.on('data', (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);

    while (buffer.length >= frameSize) {
      const frameData = buffer.slice(0, frameSize);
      buffer = buffer.slice(frameSize);

      // Convert raw RGB to ImageData
      const imageData = ctx.createImageData(targetWidth, targetHeight);
      for (let i = 0; i < targetWidth * targetHeight; i++) {
        imageData.data[i * 4] = frameData[i * 3];     // R
        imageData.data[i * 4 + 1] = frameData[i * 3 + 1]; // G
        imageData.data[i * 4 + 2] = frameData[i * 3 + 2]; // B
        imageData.data[i * 4 + 3] = 255;                   // A
      }

      // Load into display and render
      display.loadFromImageData(imageData);
      display.draw();
      
      frameCount++;
      
      // Calculate when next frame should be displayed
      const expectedTime = startTime + (frameCount * frameDuration);
      const currentTime = Date.now();
      const delay = expectedTime - currentTime;
      
      // Sleep to maintain correct framerate
      if (delay > 0) {
        const sleepUntil = Date.now() + delay;
        while (Date.now() < sleepUntil) {
          // Busy wait for precise timing
        }
      }
    }
  });

  ffmpeg.on('close', (code) => {
    audio.kill(); // Stop audio when video ends
    process.stdout.write('\x1b[?25h\x1b[0m\n');
    console.log(`\n[DONE] Played ${frameCount} frames`);
    process.exit(0);
  });

  ffmpeg.on('error', (err) => {
    audio.kill();
    console.error('[ERROR]', err.message);
    process.exit(1);
  });

  // Kill audio if user interrupts
  process.on('SIGINT', () => {
    audio.kill();
    ffmpeg.kill();
    process.stdout.write('\x1b[?25h\x1b[0m\n');
    console.log('\n[STOPPED] Playback interrupted');
    process.exit(0);
  });
}

// CLI
const videoPath = process.argv[2] || 'video.mp4';
const width = parseInt(process.argv[3]) || 200;
const fps = process.argv[4] ? parseInt(process.argv[4]) : null; // null = auto-detect

playVideo(videoPath, width, fps);

module.exports = TermDisplay;