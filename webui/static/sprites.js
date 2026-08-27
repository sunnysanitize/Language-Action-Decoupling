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

/* Four bodies, one per seat, drawn as head-and-shoulders busts: the desk is
 * painted over the bottom of each, so what you actually see is a person
 * behind a monitor from the chest up.
 *
 * Proportions are adult, not chibi. An earlier pass gave these heads eleven
 * of the twenty rows, which is the ratio of a game mascot; a person reads as
 * a person at about a third. Head and neck now take eight rows and the torso
 * twelve, which is what buys room for a real shoulder line -- and the
 * shoulder line is most of what makes a 16px figure look like an adult in an
 * office rather than a toy.
 *
 * Nobody wears a tie. This is a quant desk: the dress code runs from a jacket
 * with an open collar at the very top to a button-down with the sleeves
 * pushed up, and a tie would be a costume from a different decade. The
 * gradient is real but narrow, which is the point -- the founder is the only
 * one dressed for anybody outside the building.
 *
 *   founder   jacket, open collar, no tie   -- he meets the pension funds
 *   boss      quarter-zip over a collar     -- the actual PM uniform
 *   trader a  button-down, sleeves rolled, headset
 *   trader b  button-down, short sleeves, glasses
 *
 * Each is 16 wide and 20 tall, in two frames -- arms down, arms up. The arms
 * move by exactly one row between frames; alternating at ~5Hz is the "typing"
 * animation, which is the only motion an agent that is thinking has to show.
 *
 * Three channels separate the four, and none of them is hue: the hairline,
 * the one accessory, and the lightness of the cloth. See PALETTES below.
 */

/* Founder: mid-fifties, hair gone back off a high forehead. Suit jacket with
 * lapels over an open collar -- the shirt shows as a V at the throat and is
 * the only white on him. */
const BODY_FOUNDER_A = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHSSSSSSHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCDDAADDCCCO.',
  '.OCCCCDAADCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

const BODY_FOUNDER_B = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHSSSSSSHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCDDAADDCCCO.',
  '.OCCCCDAADCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

/* Boss: forties, full head of hair. Quarter-zip pullover over a collar, zip
 * pulled halfway. This is not a joke about hedge funds; it is what a portfolio
 * manager is wearing right now. */
const BODY_BOSS_A = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCCCSSCCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

const BODY_BOSS_B = [
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHSEESEESO...',
  '...OHSSMMSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCCCSSCCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OCCCCCAACCCCCO.',
  '.OSSCCCAACCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

/* Trader A: thirties, button-down with the sleeves pushed up -- two rows of
 * bare forearm. Headset: band over the crown, cups outside the head outline,
 * boom mic at the mouth. He is the one on the phone to brokers. */
const BODY_TRADER_A_A = [
  '....OAAAAAAO....',
  '...OAHHHHHHAO...',
  '..AOHSSSSSSHOA..',
  '..AOHSEESEESOA..',
  '...OHSSMMSSSOA..',
  '...OHSSSSSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCCCSSCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

const BODY_TRADER_A_B = [
  '....OAAAAAAO....',
  '...OAHHHHHHAO...',
  '..AOHSSSSSSHOA..',
  '..AOHSEESEESOA..',
  '...OHSSMMSSSOA..',
  '...OHSSSSSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCCCSSCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

/* Trader B: late twenties, taller crown of hair, glasses drawn as frames
 * around both eyes so the eyes still read. Short sleeves -- three rows of
 * forearm against A's two, which is a second silhouette difference for the
 * case where the head is turned away behind a bubble. */
const BODY_TRADER_B_A = [
  '....OOOOOOOO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHAEEAEEAO...',
  '...OHSSMMSSSO...',
  '...OHSSSSSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCCCSSCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
  '.OOOOOOOOOOOOOO.',
];

const BODY_TRADER_B_B = [
  '....OOOOOOOO....',
  '...OHHHHHHHHO...',
  '...OHSSSSSSHO...',
  '...OHAEEAEEAO...',
  '...OHSSMMSSSO...',
  '...OHSSSSSSSO...',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
  '..OOOOCSSCOOOO..',
  '.OCCCCCSSCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OSSCCCCCCCCSSO.',
  '.OCCCCCCCCCCCCO.',
  '.OCCCCCCCCCCCCO.',
  '.ODDDDDDDDDDDDO.',
  '.ODDDDDDDDDDDDO.',
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
  founder: [BODY_FOUNDER_A, BODY_FOUNDER_B],
  boss: [BODY_BOSS_A, BODY_BOSS_B],
  trader_a: [BODY_TRADER_A_A, BODY_TRADER_A_B],
  trader_b: [BODY_TRADER_B_A, BODY_TRADER_B_B],
};

/* One palette per actor. Three channels separate the four, and none of them
 * is hue -- everyone is in navy, grey and white, because that is what the
 * room actually contains:
 *
 *   hairline    receding | full | headset band | tall crown
 *   accessory   open-collar shirt | zip | headset | glasses
 *   value       #66748e | #8b96a8 | #b8c1ce | #eef1f6
 *
 * The value ladder is the room's doing rather than a taste call. The floor is
 * #0f1e33 and the wall behind the two supervisors is #1b3050, so dark cloth
 * on dark ground is a silhouette with nothing inside it. Every garment clears
 * 2.8:1 against both, and every rung is at least 1.5:1 from its neighbour --
 * so the four are separable in a greyscale screenshot, with the hairline as
 * the backup when two of them overlap on screen.
 *
 * A is the one detail each person gets, and it is a different thing on each:
 * the founder's shirt at his open collar, the boss's zip, the headset, the
 * glasses. That is why the founder's A is white and the boss's is near-black
 * -- each has to contrast with whatever it is drawn on, not with each other. */
const PALETTES = {
  founder: { O: '#010306', H: '#b9b3a4', S: '#e8c4a0', E: '#010306', M: '#7a4a38', C: '#66748e', D: '#465166', A: '#eef1f6' },
  boss:    { O: '#010306', H: '#6b5540', S: '#d9b494', E: '#010306', M: '#7a4a38', C: '#8b96a8', D: '#626d80', A: '#2b3444' },
  trader_a:{ O: '#010306', H: '#4f4438', S: '#e6cdb2', E: '#010306', M: '#7a4a38', C: '#b8c1ce', D: '#8894a6', A: '#dfe5ec' },
  trader_b:{ O: '#010306', H: '#5a4636', S: '#c9a180', E: '#010306', M: '#7a4a38', C: '#eef1f6', D: '#bcc6d4', A: '#3f4a5a' },
};

const PROP_PALETTE = {
  O: '#010306', F: '#2a4266', G: '#1b3050',
  L: '#3fd1a4', T: '#5a4636',
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
