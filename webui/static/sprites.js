/* Pixel sprites for the trading floor.
 *
 * Same shape as pixel-agents' sprite data -- a grid of palette keys plus a
 * key->colour map -- but drawn here rather than loaded from PNGs, because
 * their character art is a licensed pack (JIK-A-4's Metro City) that this repo
 * does not ship. Keeping the sprites as text has a second advantage: a palette
 * is per-actor, so one body is drawn four times in four colour schemes instead
 * of four sprite sheets going out of sync.
 *
 * Keys:
 *   .  transparent    O  outline        H  hair
 *   S  skin           E  eye            M  mouth
 *   C  clothes        D  clothes shade  A  accent (tie / lanyard)
 *   G  glass/screen   F  frame          L  leaf     T  stem/trunk
 *
 * Every grid is 16 wide. Two frames per body: arms down, arms up. Alternating
 * them at ~5Hz is the "typing" animation, which is the only motion an agent
 * that is thinking has to show.
 */

'use strict';

/* Trader: shirt sleeves, forearms on the desk. */
const BODY_DESK_A = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSSSSSSO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '......OSSO......',
  '...OOOCCCCOOO...',
  '..OCCCCCCCCCCO..',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OSSCCCAACCCSSO.',
  '.OSSCCCCCCCSSO..',
  '..ODDDDDDDDDO...',
  '..ODDDDDDDDDO...',
  '..OOOOOOOOOOO...',
];

const BODY_DESK_B = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSSSSSSO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '......OSSO......',
  '...OOOCCCCOOO...',
  '.OSSCCCCCCCSSO..',
  '.OSSCCCAACCCSSO.',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCCCCCCCO..',
  '..ODDDDDDDDDO...',
  '..ODDDDDDDDDO...',
  '..OOOOOOOOOOO...',
];

/* Supervisor: jacket with lapels and a wider shoulder line. Same head, so a
 * palette swap still reads as the same species of person. */
const BODY_SUIT_A = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSSSSSSO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '......OSSO......',
  '..OOODSSSDOOO...',
  '.OCCCDDSSDDCCCO.',
  '.OCCCCDAADCCCCO.',
  '.OCCCCDAADCCCCO.',
  '.OSCCCDAADCCCSO.',
  '.OSCCCCAACCCCSO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

const BODY_SUIT_B = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSSSSSSO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '......OSSO......',
  '..OOODSSSDOOO...',
  '.OSCCDDSSDDCCSO.',
  '.OSCCCDAADCCCSO.',
  '.OCCCCDAADCCCCO.',
  '.OCCCCDAADCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

const MONITOR = [
  '..OOOOOOOOOOOO..',
  '..OFFFFFFFFFFO..',
  '..OFGGGGGGGGFO..',
  '..OFGGGGGGGGFO..',
  '..OFGGGGGGGGFO..',
  '..OFGGGGGGGGFO..',
  '..OFGGGGGGGGFO..',
  '..OFFFFFFFFFFO..',
  '..OOOOOOOOOOOO..',
  '......OFFO......',
  '....OOFFFFOO....',
  '....OOOOOOOO....',
];

const PLANT = [
  '......LL........',
  '...LLLLLLL......',
  '..LLLLLLLLL.....',
  '.LLLLLTLLLLL....',
  '..LLLLTLLLL.....',
  '....LLTLLL......',
  '......T.........',
  '......T.........',
  '....OOTOO.......',
  '....OFFFO.......',
  '....OFFFO.......',
  '.....OOO........',
];

const BODIES = {
  desk: [BODY_DESK_A, BODY_DESK_B],
  suit: [BODY_SUIT_A, BODY_SUIT_B],
};

/* One palette per actor. The hierarchy is colour-coded top to bottom: the
 * founder in the firm's violet, the boss in a cooler blue, the two traders in
 * the amber/green pair the label legend already uses elsewhere on the desk. */
const PALETTES = {
  founder: { O: '#0a0a14', H: '#c9c9d6', S: '#e8b88f', E: '#0a0a14', M: '#8a5a44', C: '#6030ff', D: '#3f1fb0', A: '#ffd23f' },
  boss:    { O: '#0a0a14', H: '#4a3a2a', S: '#d9a273', E: '#0a0a14', M: '#7a4a38', C: '#3794ff', D: '#1f5fb0', A: '#ecc' },
  trader_a:{ O: '#0a0a14', H: '#2a2a3a', S: '#f0c9a0', E: '#0a0a14', M: '#8a5a44', C: '#ff8d14', D: '#b35f06', A: '#1e1e2e' },
  trader_b:{ O: '#0a0a14', H: '#6a3a2a', S: '#c98a5f', E: '#0a0a14', M: '#7a4a38', C: '#89d185', D: '#4f9a4b', A: '#1e1e2e' },
};

const PROP_PALETTE = {
  O: '#0a0a14', F: '#2a2a3a', G: '#12121e',
  L: '#4f9a4b', T: '#6a4a2a',
};

/* Draws a grid at (x, y) in canvas pixels, one grid cell per `scale` pixels.
 * Integer coordinates only -- a half-pixel offset is what turns crisp pixel
 * art into a blurry mess, and no amount of imageSmoothingEnabled = false
 * rescues it. */
function drawSprite(ctx, grid, palette, x, y, scale, alpha = 1) {
  const previousAlpha = ctx.globalAlpha;
  if (alpha !== 1) ctx.globalAlpha = alpha;
  const left = Math.round(x);
  const top = Math.round(y);
  for (let row = 0; row < grid.length; row += 1) {
    const line = grid[row];
    let column = 0;
    while (column < line.length) {
      const key = line[column];
      if (key === '.') { column += 1; continue; }
      // Run-length the row: a solid band of shirt is one fillRect instead of
      // sixteen, which matters at 60fps with four characters and props.
      let run = 1;
      while (column + run < line.length && line[column + run] === key) run += 1;
      const colour = palette[key];
      if (colour) {
        ctx.fillStyle = colour;
        ctx.fillRect(left + column * scale, top + row * scale, run * scale, scale);
      }
      column += run;
    }
  }
  ctx.globalAlpha = previousAlpha;
}

window.PixelSprites = { BODIES, PALETTES, PROP_PALETTE, MONITOR, PLANT, drawSprite };
