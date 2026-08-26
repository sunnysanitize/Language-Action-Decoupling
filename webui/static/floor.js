/* The trading floor: a pixel-art office that acts out a recorded episode.
 *
 * Split on purpose. The office -- floor, walls, desks, characters, the
 * reporting lines between them -- is canvas, drawn from the sprite grids in
 * sprites.js at an integer scale so it stays pixel-crisp. The speech bubbles
 * are DOM nodes positioned over the canvas, because they carry paragraphs of
 * model reasoning rather than the 11x13 icon sprites pixel-agents uses; laying
 * that out in canvas would mean writing a text engine to get wrapping,
 * scrolling and selection that the browser already has.
 *
 * The visual grammar carries the role contract, and getting it wrong would
 * illustrate the opposite of the experiment:
 *
 *   solid bubble   something that actually reached another agent
 *   dashed bubble  private_reasoning -- never shown to anyone
 *   lit wire       the channel it travelled down
 *
 * The founder has no wire to a trader because there isn't one. The boss's
 * bubbles reach traders; its scratchpad does not.
 */

'use strict';

(function () {
  const { BODIES, PALETTES, PROP_PALETTE, MONITOR, PLANT, drawSprite } = window.PixelSprites;

  // Small logical stage, large integer scale. 240 wide means a ~760px column
  // gets scale 3 rather than the scale 1 a 420-wide stage would round down to,
  // and a character ends up 48 screen pixels tall instead of 16. Pixel art
  // that has to be squinted at is just a small picture.
  const STAGE = { w: 240, h: 168 };
  const WALL_HEIGHT = 22;
  const TILE = 12;

  // Where each actor sits, in stage pixels. Rows are the hierarchy: founder
  // over portfolio manager over traders. That vertical order is the whole
  // independent variable, so it is the one thing about this layout that is not
  // free to change for looks.
  const SEATS = {
    ken_griffin: { x: 120, y: 36, body: 'suit', desk: 26, label: 'above' },
    boss_1: { x: 120, y: 88, body: 'suit', desk: 26, label: 'above' },
    trader_a: { x: 44, y: 138, body: 'desk', desk: 28, label: 'below' },
    trader_b: { x: 196, y: 138, body: 'desk', desk: 28, label: 'below' },
  };

  // Who can speak to whom. Drawn as wires, lit when a beat travels one.
  const WIRES = [
    ['ken_griffin', 'boss_1'],
    ['boss_1', 'trader_a'],
    ['boss_1', 'trader_b'],
    ['trader_a', 'trader_b'],
  ];

  const COLORS = {
    wall: '#221f33',
    wallTrim: '#4a4a6a',
    wallDark: '#191527',
    carpet: '#2a2a3a',
    carpetAccent: '#24243333',
    deskTop: '#5a4230',
    deskSide: '#3d2c20',
    deskEdge: '#0a0a14',
    wire: '#3a3a55',
    wireLive: '#746fff',
    platform: '#2f2b44',
  };

  const PHASE_TINT = {
    brief: '#6030ff',
    signal: '#3794ff',
    share: '#cca700',
    trade: '#89d185',
    report: '#ff8d14',
    market: '#d14249',
  };

  class FloorView {
    constructor(root) {
      this.root = root;
      this.canvas = root.querySelector('canvas');
      this.ctx = this.canvas.getContext('2d');
      this.bubbleLayer = root.querySelector('.bubble-layer');
      this.scene = null;
      this.roundIndex = 0;
      this.beatIndex = 0;
      this.playing = false;
      this.speed = 1;
      this.scale = 2;
      this.frame = 0;
      this.frameClock = 0;
      this.beatClock = 0;
      this.lastTime = 0;
      this.active = new Set();     // actors mid-beat, for the typing animation
      this.liveWires = new Map();  // "a>b" -> remaining seconds lit
      this.bubbles = new Map();    // actor -> { beat, node, age }
      this.onChange = null;
      this.loop = this.loop.bind(this);
      this.resize = this.resize.bind(this);
      window.addEventListener('resize', this.resize);
      requestAnimationFrame(this.loop);
    }

    /* ------------------------------------------------------------- scene */

    load(scene) {
      const sameEpisode = this.scene && this.scene.id === scene.id;
      this.scene = scene;
      if (!sameEpisode) {
        this.roundIndex = 0;
        this.beatIndex = 0;
        this.clearBubbles();
      } else {
        // A live episode grows while it plays. Keep the cursor where it is.
        this.roundIndex = Math.min(this.roundIndex, scene.rounds.length - 1);
      }
      this.resize();
      this.applyBeat();
      this.emit();
    }

    get round() {
      if (!this.scene || !this.scene.rounds.length) return null;
      return this.scene.rounds[Math.min(this.roundIndex, this.scene.rounds.length - 1)];
    }

    get beats() {
      const round = this.round;
      return round ? round.beats : [];
    }

    get beat() {
      return this.beats[this.beatIndex] || null;
    }

    emit() {
      if (this.onChange) this.onChange(this);
    }

    /* ---------------------------------------------------------- playback */

    play() { this.playing = true; this.beatClock = 0; this.emit(); }
    pause() { this.playing = false; this.emit(); }
    toggle() { this.playing ? this.pause() : this.play(); }

    step(delta) {
      const beats = this.beats;
      let next = this.beatIndex + delta;
      if (next >= beats.length) {
        if (this.roundIndex + 1 < this.scene.rounds.length) {
          this.roundIndex += 1;
          this.beatIndex = 0;
          this.clearBubbles();
        } else {
          this.beatIndex = beats.length - 1;
          this.playing = false;
        }
      } else if (next < 0) {
        if (this.roundIndex > 0) {
          this.roundIndex -= 1;
          this.beatIndex = Math.max(0, this.beats.length - 1);
          this.clearBubbles();
        } else {
          this.beatIndex = 0;
        }
      } else {
        this.beatIndex = next;
      }
      this.beatClock = 0;
      this.applyBeat();
      this.emit();
    }

    goToRound(index) {
      if (!this.scene) return;
      this.roundIndex = Math.max(0, Math.min(index, this.scene.rounds.length - 1));
      this.beatIndex = 0;
      this.beatClock = 0;
      this.clearBubbles();
      this.applyBeat();
      this.emit();
    }

    // How long the current beat holds the stage. Reading time, not a constant:
    // a two-word P&L line and a 400-character scratchpad entry should not get
    // the same second and a half.
    dwellSeconds() {
      const beat = this.beat;
      if (!beat) return 1;
      const words = String(beat.text || '').split(/\s+/).length;
      const base = beat.kind === 'think' ? 1.4 : 0.9;
      return Math.min(7, base + words * 0.055) / this.speed;
    }

    /* ----------------------------------------------------------- bubbles */

    applyBeat() {
      const beat = this.beat;
      if (!beat) return;
      this.active.clear();
      if (SEATS[beat.actor]) this.active.add(beat.actor);

      if (beat.to && SEATS[beat.to]) {
        this.liveWires.set(`${beat.actor}>${beat.to}`, 1.2);
      } else if (beat.broadcast) {
        for (const [from, to] of WIRES) {
          if (from === beat.actor) this.liveWires.set(`${from}>${to}`, 1.2);
        }
      }
      if (SEATS[beat.actor]) this.setBubble(beat.actor, beat);
    }

    // One bubble at a time. Two of these boxes are wider than half the stage,
    // so a room that keeps every speaker's last line ends up as overlapping
    // paper with the characters hidden underneath. The phase rail carries the
    // continuity that the extra bubbles were trying to.
    setBubble(actor, beat) {
      for (const entry of this.bubbles.values()) entry.node.remove();
      this.bubbles.clear();
      const node = this.buildBubble(beat);
      this.bubbleLayer.append(node);
      this.bubbles.set(actor, { beat, node });
      // offsetWidth/offsetHeight are only meaningful once the node is in the
      // document, so placement happens after the append, not during the build.
      this.positionBubbles();
    }

    buildBubble(beat) {
      const node = document.createElement('div');
      node.className = `bubble bubble-${beat.kind}`;
      if (beat.label) node.classList.add(`bubble-flag-${beat.label}`);

      const head = document.createElement('div');
      head.className = 'bubble-head';
      const who = this.actorName(beat.actor);
      let verb = { think: 'thinks', say: 'says', act: 'does', signal: 'draws', pnl: 'books', label: '' }[beat.kind] || '';
      if (beat.kind === 'say' && beat.to) verb = `to ${this.actorName(beat.to)}`;
      else if (beat.kind === 'say' && beat.broadcast) verb = 'to the desk';
      head.textContent = verb ? `${who} ${verb}` : who;
      node.append(head);

      const body = document.createElement('div');
      body.className = 'bubble-body';
      body.textContent = beat.text || '';
      node.append(body);

      const tags = [];
      if (beat.kind === 'think') tags.push(['private', 'seen by nobody else']);
      if (beat.shared_signal !== undefined && beat.shared_signal !== null) {
        tags.push([`shares ${beat.shared_signal > 0 ? '+1' : '-1'}`, 'the structured signal field']);
      }
      if (beat.kind === 'say' && beat.channel === 'public' && beat.shared_signal === null) {
        tags.push(['no signal', 'spoke without sharing the draw']);
      }
      if (beat.label === 'withheld') {
        tags.push([beat.costly ? 'costly withholding' : 'withheld', 'the label the detector predicts']);
      }
      if (beat.label === 'misreported') tags.push(['misreported', 'report differs from execution']);
      if (beat.data && beat.data.clipped) tags.push(['budget clipped', 'the ask exceeded the budget']);
      if (tags.length) {
        const row = document.createElement('div');
        row.className = 'bubble-tags';
        for (const [text, title] of tags) {
          const tag = document.createElement('span');
          tag.textContent = text;
          tag.title = title;
          row.append(tag);
        }
        node.append(row);
      }
      return node;
    }

    actorName(id) {
      if (id === 'market') return 'The market';
      const actor = (this.scene ? this.scene.actors : []).find((item) => item.id === id);
      return actor ? actor.name : id;
    }

    clearBubbles() {
      for (const entry of this.bubbles.values()) entry.node.remove();
      this.bubbles.clear();
    }

    positionBubbles() {
      const scale = this.scale;
      const stageWidth = STAGE.w * scale;
      const stageHeight = STAGE.h * scale;

      for (const [actor, entry] of this.bubbles) {
        const seat = SEATS[actor];
        if (!seat) continue;
        const node = entry.node;
        node.style.maxWidth = `${Math.min(300, Math.max(170, stageWidth * 0.45))}px`;

        const width = node.offsetWidth;
        const height = node.offsetHeight;
        const centreX = seat.x * scale;

        // The speaker's own footprint: sprite plus desk. A bubble is no use if
        // it is sitting on the character it is coming out of.
        const speaker = {
          left: (seat.x - seat.desk - 4) * scale,
          right: (seat.x + seat.desk + 4) * scale,
          top: (seat.y - 22) * scale,
          bottom: (seat.y + 15) * scale,
        };

        const above = seat.label === 'above';
        let top = above
          ? seat.y * scale - height - 8 * scale
          : seat.y * scale + 10 * scale;
        top = Math.max(2, Math.min(stageHeight - height - 2, top));

        let left = Math.max(2, Math.min(stageWidth - width - 2, centreX - width / 2));

        // If the clamp pushed the box onto the speaker, slide it to whichever
        // side of the room has more space. Only vertical overlap matters --
        // side by side is fine and reads as someone talking across the floor.
        const overlapsVertically = top < speaker.bottom && top + height > speaker.top;
        if (overlapsVertically) {
          const roomLeft = speaker.left;
          const roomRight = stageWidth - speaker.right;
          left = roomRight >= roomLeft
            ? Math.min(stageWidth - width - 2, speaker.right + 4)
            : Math.max(2, speaker.left - width - 4);
          left = Math.max(2, Math.min(stageWidth - width - 2, left));
        }

        node.style.left = `${Math.round(left)}px`;
        node.style.top = `${Math.round(top)}px`;
        node.classList.toggle('bubble-above', above);
        node.classList.toggle('bubble-below', !above);
        // Hide the tail when the box had to move beside the speaker: a tail
        // pointing sideways out of the bottom edge points at nothing.
        node.classList.toggle('bubble-notail', overlapsVertically);
        const tailX = Math.max(8, Math.min(width - 16, centreX - left - 5));
        node.style.setProperty('--tail-x', `${Math.round(tailX)}px`);
      }
    }

    /* ------------------------------------------------------------ render */

    resize() {
      // The wrapper, never this.root: the stage is flex:none and sized by the
      // canvas inside it, so measuring it to decide how big the canvas should
      // be is a loop that settles on whatever it started at.
      const host = this.root.parentElement || this.root;
      const width = host.clientWidth - 16;
      if (width <= 0) return;
      // Integer scale only. A fractional one puts sprite edges on half pixels
      // and the whole point of the art is that they land on whole ones.
      this.scale = Math.max(1, Math.floor(width / STAGE.w));
      const ratio = window.devicePixelRatio || 1;
      this.canvas.style.width = `${STAGE.w * this.scale}px`;
      this.canvas.style.height = `${STAGE.h * this.scale}px`;
      this.canvas.width = STAGE.w * this.scale * ratio;
      this.canvas.height = STAGE.h * this.scale * ratio;
      this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      this.ctx.imageSmoothingEnabled = false;
      this.bubbleLayer.style.width = `${STAGE.w * this.scale}px`;
      this.bubbleLayer.style.height = `${STAGE.h * this.scale}px`;
      this.positionBubbles();
    }

    loop(time) {
      const delta = Math.min(0.1, (time - this.lastTime) / 1000 || 0);
      this.lastTime = time;

      this.frameClock += delta;
      if (this.frameClock > 0.2) { this.frameClock = 0; this.frame ^= 1; }

      for (const [key, remaining] of this.liveWires) {
        const next = remaining - delta;
        if (next <= 0) this.liveWires.delete(key);
        else this.liveWires.set(key, next);
      }

      if (this.playing && this.scene) {
        this.beatClock += delta;
        if (this.beatClock >= this.dwellSeconds()) { this.beatClock = 0; this.step(1); }
      }

      this.draw();
      requestAnimationFrame(this.loop);
    }

    draw() {
      const ctx = this.ctx;
      const scale = this.scale;
      ctx.clearRect(0, 0, STAGE.w * scale, STAGE.h * scale);
      this.drawRoom(ctx, scale);
      for (const [from, to] of WIRES) this.drawWire(ctx, scale, from, to);
      for (const id of Object.keys(SEATS)) this.drawStation(ctx, scale, id);
      this.drawTicker(ctx, scale);
    }

    drawRoom(ctx, scale) {
      const px = (v) => Math.round(v * scale);

      ctx.fillStyle = COLORS.wall;
      ctx.fillRect(0, 0, px(STAGE.w), px(WALL_HEIGHT));
      ctx.fillStyle = COLORS.wallDark;
      for (let x = 0; x < STAGE.w; x += TILE * 2) {
        ctx.fillRect(px(x), 0, px(TILE), px(WALL_HEIGHT));
      }
      ctx.fillStyle = COLORS.wallTrim;
      ctx.fillRect(0, px(WALL_HEIGHT - 3), px(STAGE.w), px(3));

      ctx.fillStyle = COLORS.carpet;
      ctx.fillRect(0, px(WALL_HEIGHT), px(STAGE.w), px(STAGE.h - WALL_HEIGHT));
      ctx.fillStyle = COLORS.carpetAccent;
      for (let y = WALL_HEIGHT; y < STAGE.h; y += TILE) {
        for (let x = 0; x < STAGE.w; x += TILE) {
          if (((x / TILE) + (y / TILE)) % 2 === 0) ctx.fillRect(px(x), px(y), px(TILE), px(TILE));
        }
      }

      // Raised platforms under the two supervisors. Standing higher than the
      // people you rank is the oldest office grammar there is.
      for (const id of ['ken_griffin', 'boss_1']) {
        const seat = SEATS[id];
        ctx.fillStyle = COLORS.platform;
        ctx.fillRect(px(seat.x - 42), px(seat.y - 14), px(84), px(38));
        ctx.fillStyle = COLORS.deskEdge;
        ctx.fillRect(px(seat.x - 42), px(seat.y + 24), px(84), px(1));
      }

      drawSprite(ctx, PLANT, PROP_PALETTE, px(4), px(WALL_HEIGHT + 2), scale);
      drawSprite(ctx, PLANT, PROP_PALETTE, px(STAGE.w - 20), px(WALL_HEIGHT + 2), scale);
    }

    drawWire(ctx, scale, from, to) {
      const a = SEATS[from];
      const b = SEATS[to];
      if (!a || !b) return;
      const lit = this.liveWires.get(`${from}>${to}`) || this.liveWires.get(`${to}>${from}`) || 0;
      const px = (v) => Math.round(v * scale);
      ctx.fillStyle = lit > 0 ? COLORS.wireLive : COLORS.wire;
      const thickness = Math.max(1, Math.round(scale * (lit > 0 ? 2 : 1)));

      if (a.y === b.y) {
        const midY = px(a.y + 20);
        const left = px(Math.min(a.x, b.x));
        const right = px(Math.max(a.x, b.x));
        ctx.fillRect(left, midY, right - left, thickness);
      } else {
        const midY = px((a.y + b.y) / 2 + 6);
        ctx.fillRect(px(a.x), px(a.y + 14), thickness, midY - px(a.y + 14));
        const left = Math.min(px(a.x), px(b.x));
        const right = Math.max(px(a.x), px(b.x));
        ctx.fillRect(left, midY, right - left + thickness, thickness);
        ctx.fillRect(px(b.x), midY, thickness, px(b.y - 14) - midY);
      }
    }

    drawStation(ctx, scale, id) {
      const seat = SEATS[id];
      const actor = (this.scene ? this.scene.actors : []).find((item) => item.id === id);
      const palette = PALETTES[actor ? actor.palette : 'trader_a'] || PALETTES.trader_a;
      const px = (v) => Math.round(v * scale);

      const isActive = this.active.has(id);
      const body = BODIES[seat.body][isActive ? this.frame : 0];
      drawSprite(ctx, body, palette, px(seat.x - 8), px(seat.y - 19), scale, isActive ? 1 : 0.85);

      // Desk in front, drawn after the body so the character sits behind it.
      const half = seat.desk;
      ctx.fillStyle = COLORS.deskEdge;
      ctx.fillRect(px(seat.x - half - 1), px(seat.y + 1), px(half * 2 + 2), px(13));
      ctx.fillStyle = COLORS.deskTop;
      ctx.fillRect(px(seat.x - half), px(seat.y + 2), px(half * 2), px(4));
      ctx.fillStyle = COLORS.deskSide;
      ctx.fillRect(px(seat.x - half), px(seat.y + 6), px(half * 2), px(7));

      drawSprite(ctx, MONITOR, PROP_PALETTE, px(seat.x + half - 18), px(seat.y - 6), scale, 0.9);

      // A ring on the floor marks whoever is acting right now -- the same job
      // the pulsing LED does in the jobs list.
      if (isActive) {
        ctx.fillStyle = PHASE_TINT[this.beat ? this.beat.phase : 'brief'] || COLORS.wireLive;
        ctx.fillRect(px(seat.x - half - 3), px(seat.y - 22), px(1), px(38));
        ctx.fillRect(px(seat.x + half + 2), px(seat.y - 22), px(1), px(38));
      }
    }

    drawTicker(ctx, scale) {
      const round = this.round;
      if (!round) return;
      const px = (v) => Math.round(v * scale);
      const beat = this.beat;
      const reached = beat && ['market'].includes(beat.phase);
      const direction = round.world.market_direction;

      ctx.fillStyle = '#12121e';
      ctx.fillRect(0, px(STAGE.h - 12), px(STAGE.w), px(12));
      ctx.fillStyle = COLORS.wallTrim;
      ctx.fillRect(0, px(STAGE.h - 12), px(STAGE.w), px(1));

      // The market direction is hidden until the market beat plays. Showing it
      // during the share phase would hand the viewer information no agent had.
      const cells = 28;
      for (let index = 0; index < cells; index += 1) {
        ctx.fillStyle = !reached ? '#2a2a3a' : (direction > 0 ? '#89d185' : '#d14249');
        const height = !reached ? 1 : (direction > 0 ? 2 + (index % 4) : 2 + ((cells - index) % 4));
        ctx.fillRect(px(4 + index * 8), px(STAGE.h - 4 - height), px(5), px(height));
      }
    }
  }

  window.FloorView = FloorView;
  window.FloorSeats = SEATS;
})();
