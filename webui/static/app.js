/* MarketArena control desk.
 *
 * Vanilla DOM, no framework and no build step, for the same reason the server
 * is stdlib-only: this repo's simulator runs on a bare checkout and the desk
 * had no business being the thing that introduced a toolchain.
 *
 * The form is not written out by hand. GET /api/state returns the field specs
 * from webui/commands.py and the form is generated from them, so a parameter
 * cannot exist in the page without the validator that guards it -- and cannot
 * be added to the validator without appearing here.
 */

'use strict';

const state = {
  commands: [],
  environment: null,
  runs: [],
  jobs: [],
  command: null,        // selected command name
  values: {},           // command name -> { field -> value }
  job: null,            // selected job id
  logOffset: 0,
  logSeen: null,        // job id the console is currently showing
  run: null,            // selected run path
  detail: null,
  filter: '',
};

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child == null) continue;
    node.append(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return node;
};

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch (_) { payload = { error: text }; }
  if (!response.ok) throw new Error((payload && payload.error) || `HTTP ${response.status}`);
  return payload;
}

function toast(message, kind = '') {
  const node = el('div', { class: `toast ${kind}`, text: message });
  $('toasts').append(node);
  setTimeout(() => node.remove(), kind === 'bad' ? 9000 : 4500);
}

/* --------------------------------------------------------------- env chips */

function renderEnvironment() {
  const env = state.environment;
  const box = $('env-chips');
  box.replaceChildren();
  if (!env) return;

  const broken = !!env.provider_problem;
  const providerChip = chip(broken ? 'bad' : 'ok', broken ? 'bad' : 'ok',
    'Provider', broken ? 'unusable' : (env.model || 'configured'));
  providerChip.title = env.provider_problem || `${env.endpoint} / ${env.model}`;
  box.append(providerChip);

  const missing = Object.entries(env.packages).filter(([, ok]) => !ok).map(([name]) => name);
  box.append(chip(missing.length ? 'warn' : 'ok', missing.length ? 'warn' : 'ok',
    'Deps', missing.length ? `missing ${missing.join(', ')}` : 'complete'));

  box.append(chip('', '', 'Python', env.python));
}

function chip(chipClass, ledClass, key, value) {
  return el('div', { class: `chip ${chipClass}` }, [
    el('span', { class: `led ${ledClass}` }),
    `${key} `,
    el('strong', { text: String(value) }),
  ]);
}

/* ------------------------------------------------------------ command grid */

function renderCommands() {
  const grid = $('command-grid');
  grid.replaceChildren();
  for (const command of state.commands) {
    grid.append(el('button', {
      type: 'button',
      class: command.live ? 'live' : '',
      'aria-pressed': String(command.name === state.command),
      title: command.live ? 'Spends provider tokens' : 'Local only',
      text: command.label,
      onclick: () => selectCommand(command.name),
    }));
  }
  const command = currentCommand();
  $('command-blurb').textContent = command
    ? command.blurb + (command.live ? '  [calls the model]' : '')
    : '';
}

const currentCommand = () => state.commands.find((item) => item.name === state.command) || null;

function selectCommand(name) {
  state.command = name;
  localStorage.setItem('desk.command', name);
  renderCommands();
  renderForm();
}

/* -------------------------------------------------------------------- form */

function valuesFor(command) {
  if (!state.values[command.name]) {
    const stored = JSON.parse(localStorage.getItem(`desk.values.${command.name}`) || 'null');
    const defaults = {};
    for (const field of command.fields) defaults[field.name] = field.default;
    state.values[command.name] = Object.assign(defaults, stored || {});
  }
  return state.values[command.name];
}

function setValue(command, name, value) {
  const values = valuesFor(command);
  values[name] = value;
  localStorage.setItem(`desk.values.${command.name}`, JSON.stringify(values));
  renderArgvPreview();
}

function renderForm() {
  const form = $('params');
  form.replaceChildren();
  const command = currentCommand();
  $('form-error').hidden = true;
  if (!command) return;

  $('param-count').textContent = command.fields.length
    ? `${command.fields.length} field${command.fields.length === 1 ? '' : 's'}`
    : 'none';

  const values = valuesFor(command);
  if (!command.fields.length) {
    form.append(el('div', { class: 'empty', text: 'No parameters. Press Start.' }));
  }
  for (const field of command.fields) {
    form.append(renderField(command, field, values));
  }
  $('launch').textContent = command.live ? `Start ${command.label} (live)` : `Start ${command.label}`;
  $('launch').className = command.live ? 'primary wide' : 'wide';

  // A live command against a misconfigured provider fails on its first call,
  // several seconds and one half-written run directory later. Saying so before
  // the click is cheaper than reading it out of the console afterwards.
  if (command.live && state.environment && state.environment.provider_problem) {
    showFormError(state.environment.provider_problem);
  }
  renderArgvPreview();
}

/* These messages are written for a terminal -- check_endpoint_is_live answers
 * with a paragraph explaining how to find the right endpoint -- and a
 * paragraph in a sticky bar covers the form it is warning about. The first
 * sentence is the finding; the rest is the fix, and it keeps on hover. */
function showFormError(message) {
  const box = $('form-error');
  const full = String(message);
  const firstStop = full.indexOf('. ');
  box.textContent = firstStop > 0 && full.length > 140 ? full.slice(0, firstStop + 1) : full;
  box.title = full;
  box.hidden = false;
}

function renderField(command, field, values) {
  if (field.kind === 'bool') return booleanField(command, field, values);

  const label = el('label', { for: `f-${field.name}` }, [field.label]);
  const wrap = el('div', { class: 'field' }, [label]);

  if (field.kind === 'choice') {
    wrap.append(field.choices.some((c) => c.note)
      ? dialField(command, field, values)
      : selectField(command, field, values, field.choices.map((c) => ({ value: c.value, label: c.label }))));
  } else if (field.kind === 'run' || field.kind === 'sweep') {
    const wanted = field.kind === 'sweep' ? 'sweep' : 'episode';
    const options = runOptions(wanted);
    if (!options.length) {
      wrap.append(el('div', { class: 'form-error', text: `No ${wanted} directories under runs/ yet.` }));
    } else {
      if (field.optional) options.unshift({ value: '', label: '(none)' });
      wrap.append(selectField(command, field, values, options));
    }
  } else if (field.kind === 'int') {
    wrap.append(stepperField(command, field, values));
  } else {
    wrap.append(textField(command, field, values));
  }

  const help = values.boss_capital_authority && field.setup_b_help
    ? field.setup_b_help
    : field.help;
  if (help) wrap.append(el('div', { class: 'hint', text: help }));
  return wrap;
}

function runOptions(kind) {
  return state.runs
    .filter((run) => run.kind === kind)
    .map((run) => ({
      value: run.path,
      label: kind === 'sweep'
        ? `${run.id}  [setup ${run.setup}, ${run.episodes} eps]`
        : `${run.id}  [setup ${run.setup}, p${run.pressure}, ${run.rounds_written}r]`,
    }));
}

function selectField(command, field, values, options) {
  const node = el('select', { id: `f-${field.name}`, name: field.name });
  for (const option of options) {
    node.append(el('option', {
      value: String(option.value),
      selected: String(values[field.name] ?? '') === String(option.value),
    }, [option.label]));
  }
  node.addEventListener('change', () => setValue(command, field.name, node.value));

  // The current value can legitimately be something the option list does not
  // hold: the Detail panel prefills a sweep's *child* episode, and the picker
  // only lists top-level runs. Dropping it would silently rewrite the field
  // the user just asked for, so an unlisted value is added as its own option.
  // A value that is genuinely empty still falls back to the first option.
  const current = String(values[field.name] ?? '');
  if (current && !options.some((o) => String(o.value) === current)) {
    node.prepend(el('option', { value: current, selected: true }, [current]));
    node.value = current;
  } else if (!current && options.length && !field.optional) {
    setValue(command, field.name, options[0].value);
    node.value = String(options[0].value);
  }
  return node;
}

function dialField(command, field, values) {
  const box = el('div', { class: 'pressure', role: 'group', 'aria-label': field.label });
  for (const choice of field.choices) {
    const note = values.boss_capital_authority && choice.setup_b_note
      ? choice.setup_b_note
      : choice.note;
    box.append(el('button', {
      type: 'button',
      'aria-pressed': String(String(values[field.name]) === String(choice.value)),
      onclick: () => { setValue(command, field.name, choice.value); renderForm(); },
    }, [choice.label, el('span', { class: 'note', text: note || '' })]));
  }
  return box;
}

function stepperField(command, field, values) {
  const input = el('input', {
    type: 'number',
    id: `f-${field.name}`,
    name: field.name,
    value: values[field.name] ?? '',
    placeholder: field.optional ? 'any' : '',
  });
  if (field.minimum != null) input.min = field.minimum;
  if (field.maximum != null) input.max = field.maximum;

  const nudge = (step) => {
    const base = Number(input.value === '' ? (field.default || 0) : input.value);
    let next = base + step;
    if (field.minimum != null) next = Math.max(field.minimum, next);
    if (field.maximum != null) next = Math.min(field.maximum, next);
    input.value = String(next);
    setValue(command, field.name, next);
  };
  input.addEventListener('input', () => setValue(command, field.name, input.value));

  return el('div', { class: 'stepper' }, [
    el('button', { type: 'button', tabindex: '-1', 'aria-label': `less ${field.label}`, text: '−', onclick: () => nudge(-1) }),
    input,
    el('button', { type: 'button', tabindex: '-1', 'aria-label': `more ${field.label}`, text: '+', onclick: () => nudge(1) }),
  ]);
}

function textField(command, field, values) {
  const input = el('input', {
    type: 'text',
    id: `f-${field.name}`,
    name: field.name,
    value: values[field.name] ?? '',
    placeholder: field.optional ? '(auto)' : '',
    spellcheck: 'false',
  });
  input.addEventListener('input', () => setValue(command, field.name, input.value));
  return input;
}

function booleanField(command, field, values) {
  const input = el('input', { type: 'checkbox', id: `f-${field.name}`, checked: !!values[field.name] });
  input.addEventListener('change', () => {
    setValue(command, field.name, input.checked);
    // Setup B changes the meaning of the pressure picker, so redraw contextual
    // notes immediately rather than leaving stale Setup-A budget multipliers.
    renderForm();
  });
  return el('label', { class: 'toggle', for: `f-${field.name}` }, [
    input,
    el('span', { class: 'switch', 'aria-hidden': 'true' }),
    el('span', { class: 'switch-label' }, [
      field.label,
      field.help ? el('span', { class: 'hint', text: field.help }) : null,
    ]),
  ]);
}

/* The preview is the honest answer to "what is this button about to do".
 * It is built here for display only -- the server rebuilds the argv from the
 * whitelist and never trusts anything this function produced. */
function renderArgvPreview() {
  const command = currentCommand();
  if (!command) { $('argv-preview').textContent = ''; return; }
  const values = valuesFor(command);
  const parts = command.fields
    .filter((field) => {
      const value = values[field.name];
      if (field.kind === 'bool') return !!value;
      return value !== '' && value != null;
    })
    .map((field) => {
      const flag = '--' + field.name.replace(/_/g, '-');
      return field.kind === 'bool' ? flag : `${flag} ${values[field.name]}`;
    });
  $('argv-preview').textContent = `$ python -m ${command.name === 'tests' ? 'unittest discover' : 'experiments.' + command.name} ${parts.join(' ')}`.trim();
}

/* ------------------------------------------------------------------ launch */

async function launch() {
  const command = currentCommand();
  if (!command) return;
  const button = $('launch');
  button.disabled = true;
  $('form-error').hidden = true;
  try {
    const job = await api('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: command.name, params: valuesFor(command) }),
    });
    state.job = job.id;
    state.logOffset = 0;
    state.logSeen = null;
    $('console').replaceChildren();
    toast(`${job.label} started as ${job.id}`, 'ok');
    await tick();
  } catch (error) {
    showFormError(String(error.message || error));
    toast(String(error.message || error), 'bad');
  } finally {
    button.disabled = false;
  }
}

/* -------------------------------------------------------------------- jobs */

const STATUS_LED = {
  queued: 'warn', running: 'active', succeeded: 'ok', failed: 'bad', cancelled: 'warn',
};

function renderJobs() {
  const list = $('job-list');
  list.replaceChildren();
  $('job-count').textContent = state.jobs.length
    ? `${state.jobs.filter((j) => j.status === 'running').length} running / ${state.jobs.length}`
    : '';
  if (!state.jobs.length) {
    list.append(el('div', { class: 'empty', text: 'Nothing has been started yet.' }));
    return;
  }
  for (const job of [...state.jobs].reverse()) {
    const bits = [
      el('span', { class: `led ${STATUS_LED[job.status] || ''}` }),
      el('span', { class: 'job-name', text: `${job.id}  ${job.label}` }),
    ];
    if (job.total_units) {
      bits.push(el('span', { class: 'job-time', text: `${job.done_units || 0}/${job.total_units} ${job.unit_name}` }));
    }
    bits.push(el('span', { class: 'job-time', text: `${job.seconds}s` }));

    const row = el('button', {
      type: 'button',
      class: 'job',
      'aria-pressed': String(job.id === state.job),
      onclick: () => { state.job = job.id; state.logOffset = 0; state.logSeen = null; $('console').replaceChildren(); tick(); },
    }, bits);
    list.append(row);

    if (job.total_units) {
      list.append(el('div', { class: 'progress-line' }, [progressBar(job)]));
    }
  }
}

function progressBar(job) {
  const total = Math.max(1, job.total_units || 1);
  // Above ~40 units the blocks stop being countable, so collapse to a
  // proportional bar rather than drawing 300 slivers.
  const cells = Math.min(total, 40);
  const done = Math.round(((job.done_units || 0) / total) * cells);
  const bar = el('div', { class: 'progress' });
  for (let index = 0; index < cells; index += 1) {
    const running = job.status === 'running' && index === done;
    bar.append(el('span', { class: index < done ? 'on' : (running ? 'run' : '') }));
  }
  return bar;
}

/* ----------------------------------------------------------------- console */

const LINE_RULES = [
  [/traceback|error:|failed|cannot|refus|exception|broke the response contract/i, 'l-bad'],
  [/warning|missing|skipped/i, 'l-warn'],
  [/^\[\d+\/\d+\]|^\$ |^ {2}\w+ +\w/i, 'l-meta'],
  [/\bok\b|completed|wrote |appended to|passed|^OK$/i, 'l-ok'],
];

function classify(line) {
  for (const [pattern, name] of LINE_RULES) if (pattern.test(line)) return name;
  return line.trim() ? 'l-info' : 'l-dim';
}

function appendLines(lines) {
  const box = $('console');
  const follow = $('autoscroll').checked;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const fragment = document.createDocumentFragment();
  for (const line of lines) {
    fragment.append(el('span', { class: classify(line), text: line + '\n' }));
  }
  box.append(fragment);
  if (follow && atBottom) box.scrollTop = box.scrollHeight;
}

function renderConsoleBar(job) {
  $('console-title').textContent = job ? job.id : '';
  $('console-argv').textContent = job ? job.argv.join(' ') : '';
  $('stop-job').disabled = !job || !['running', 'queued'].includes(job.status);
  if (!job) { $('console-status').replaceChildren(); return; }
  $('console-status').replaceChildren(
    el('span', { class: `led ${STATUS_LED[job.status] || ''}` }),
    document.createTextNode(` ${job.status}${job.returncode != null ? ` (exit ${job.returncode})` : ''}`),
  );
}

/* ------------------------------------------------------------------- runs */

function renderRuns() {
  const list = $('run-list');
  list.replaceChildren();
  const filter = state.filter.trim().toLowerCase();
  const visible = state.runs.filter((run) => !filter || run.id.toLowerCase().includes(filter));
  $('run-count').textContent = `${visible.length}${visible.length !== state.runs.length ? ` / ${state.runs.length}` : ''}`;
  if (!visible.length) {
    list.append(el('div', { class: 'empty', text: state.runs.length ? 'No run matches that filter.' : 'runs/ is empty.' }));
    return;
  }
  for (const run of visible) list.append(runCard(run));
}

function runCard(run) {
  const badges = [el('span', { class: `badge setup-${run.setup.toLowerCase()}`, text: `Setup ${run.setup}` })];
  const meta = [];
  if (run.kind === 'sweep') {
    badges.unshift(el('span', { class: 'badge sweep', text: run.in_progress ? 'sweep*' : 'sweep' }));
    meta.push(`${run.episodes} eps`);
    if (run.rounds) meta.push(`${run.rounds} rounds`);
    if (run.failed) badges.push(el('span', { class: 'badge failed', text: `${run.failed} failed` }));
    if (run.wall_seconds) meta.push(`${Math.round(run.wall_seconds / 60)} min`);
  } else {
    meta.push(`p${run.pressure}`, `seed ${run.seed}`, `${run.rounds_written}/${run.rounds_planned} rounds`);
    if (!run.complete) badges.push(el('span', { class: 'badge partial', text: 'partial' }));
    if (run.has_calls) meta.push('calls');
  }
  return el('button', {
    type: 'button',
    class: 'run-card',
    'aria-pressed': String(run.path === state.run),
    onclick: () => openRun(run.path),
  }, [
    el('div', { class: 'run-head' }, [el('span', { class: 'run-id', text: run.id }), ...badges]),
    el('div', { class: 'run-meta' }, meta.map((item) => el('span', { text: item }))),
  ]);
}

async function openRun(path, { push = true } = {}) {
  state.run = path;
  if (push) writeHash();
  renderRuns();
  $('detail').replaceChildren(el('div', { class: 'empty', text: 'Reading...' }));
  try {
    state.detail = await api(`/api/run?path=${encodeURIComponent(path)}`);
  } catch (error) {
    $('detail').replaceChildren(el('div', { class: 'form-error', text: String(error.message || error) }));
    return;
  }
  renderDetail();

  // Episodes can be watched; a sweep cannot. Arm the floor either way so the
  // tab explains itself instead of showing the last episode's stage.
  if (state.detail && state.detail.kind === 'episode') {
    floor.wanted = path;
    if (floor.tab === 'floor') loadScene(path);
  } else {
    floor.wanted = null;
    if (floor.view) { floor.view.pause(); }
    $('floor-empty').hidden = false;
  }
}

function stat(key, value, kind = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'k', text: key }),
    el('div', { class: `v ${kind}`, text: String(value) }),
  ]);
}

function renderDetail() {
  const box = $('detail');
  box.replaceChildren();
  const detail = state.detail;
  if (!detail) return;
  $('detail-title').textContent = detail.id;

  if (detail.kind === 'sweep') return renderSweepDetail(box, detail);
  return renderEpisodeDetail(box, detail);
}

function renderEpisodeDetail(box, detail) {
  const totals = detail.traders.reduce((acc, trader) => ({
    withheld: acc.withheld + trader.withheld,
    costly: acc.costly + trader.costly,
    misreported: acc.misreported + trader.misreported,
  }), { withheld: 0, costly: 0, misreported: 0 });

  box.append(el('div', { class: 'stat-row' }, [
    stat('Rounds', `${detail.rounds_written}/${detail.rounds_planned ?? '?'}`),
    stat('Withheld', totals.withheld, totals.withheld ? 'warn' : ''),
    stat('Costly', totals.costly, totals.costly ? 'warn' : ''),
    stat('Misreport', totals.misreported, totals.misreported ? 'bad' : ''),
    stat('Calls', detail.calls),
  ]));

  const table = el('table', { class: 'data' }, [
    el('thead', {}, [el('tr', {}, ['trader', 'rank', 'budget', 'pnl', 'msgs', 'shared', 'wh', 'costly', 'misrep']
      .map((head) => el('th', { text: head })))]),
    el('tbody', {}, detail.traders.map((trader) => el('tr', {}, [
      el('td', { text: trader.trader_id }),
      el('td', { text: trader.rank ?? '-' }),
      el('td', { text: fixed(trader.budget) }),
      el('td', { text: fixed(trader.cumulative_pnl) }),
      el('td', { text: trader.messages }),
      el('td', { text: trader.signals_shared }),
      el('td', { class: trader.withheld ? 'hot' : '', text: trader.withheld }),
      el('td', { class: trader.costly ? 'hot' : '', text: trader.costly }),
      el('td', { class: trader.misreported ? 'bad' : '', text: trader.misreported }),
    ]))),
  ]);
  box.append(el('div', { class: 'scroll' }, [table]));

  if (detail.timeline.length) {
    box.append(el('div', { class: 'strip' }, detail.timeline.map((round, index) => {
      const kind = round.misreported ? 'misreported' : round.costly ? 'costly' : round.withheld ? 'withheld' : '';
      return el('i', {
        class: kind,
        role: 'button',
        tabindex: '0',
        style: 'cursor:pointer',
        title: `round ${round.round}: firm pnl ${fixed(round.firm_pnl)}, withheld ${round.withheld}, costly ${round.costly}, misreported ${round.misreported} — click to watch it`,
        onclick: () => openOnFloor(detail.id, index),
      });
    })));
    box.append(el('div', { class: 'legend' }, [
      legendKey('var(--color-bg-thumb)', 'clean'),
      legendKey('var(--color-status-permission)', 'withheld'),
      legendKey('var(--color-warning)', 'costly'),
      legendKey('var(--color-danger)', 'misreported'),
    ]));
  }

  const supervision = Object.entries(detail.supervision || {});
  box.append(el('div', { class: 'note-line' }, [
    supervision.length
      ? `supervision: ${supervision.map(([who, n]) => `${who} x${n}`).join(', ')}; ${detail.feedback_delivered} feedback items delivered`
      : 'no supervisor traces in this run',
  ]));

  box.append(el('div', { class: 'button-row' }, [
    el('button', { class: 'small', type: 'button', text: 'Read it', onclick: () => prefill('show_run', { run: state.run }) }),
    el('button', { class: 'small', type: 'button', text: 'Replay', onclick: () => prefill('replay', { run: state.run }) }),
  ]));
}

function renderSweepDetail(box, detail) {
  const summary = detail.summary || { rows: [] };
  const failed = detail.episodes.filter((item) => !item.complete).length;
  box.append(el('div', { class: 'stat-row' }, [
    stat('Episodes', detail.episodes.length),
    stat('Trader-rounds', summary.trader_rounds ?? 0),
    stat('Incomplete', failed, failed ? 'bad' : ''),
  ]));

  box.append(el('table', { class: 'data' }, [
    el('thead', {}, [el('tr', {}, ['press', 'eps', 'rounds', 'withheld', 'costly', 'misrep']
      .map((head) => el('th', { text: head })))]),
    el('tbody', {}, summary.rows.map((row) => el('tr', {}, [
      el('td', { text: `p${row.pressure}` }),
      el('td', { text: row.episodes }),
      el('td', { text: row.trader_rounds }),
      el('td', { class: 'hot', text: percent(row.withheld_rate) }),
      el('td', { class: 'hot', text: percent(row.costly_rate) }),
      el('td', { class: row.misreported ? 'bad' : '', text: percent(row.misreported_rate) }),
    ]))),
  ]));
  box.append(el('div', { class: 'note-line', text: 'Rates are over trader-rounds, recomputed from rounds.jsonl. The significance tests live in experiments.report.' }));

  box.append(el('div', { class: 'button-row' }, [
    el('button', { class: 'small', type: 'button', text: 'Report', onclick: () => prefill('report', { sweep: state.run }) }),
    el('button', { class: 'small', type: 'button', text: 'Findings', onclick: () => prefill('findings', { control: state.run }) }),
    el('button', { class: 'small', type: 'button', text: 'Capital check', onclick: () => prefill('capital_check', { sweep: state.run }) }),
  ]));

  box.append(el('div', { class: 'scroll' }, [el('table', { class: 'data' }, [
    el('thead', {}, [el('tr', {}, ['episode', 'p', 'seed', 'rounds'].map((head) => el('th', { text: head })))]),
    el('tbody', {}, detail.episodes.map((episode) => el('tr', {}, [
      el('td', {}, [el('button', {
        class: 'small', type: 'button', text: episode.id,
        onclick: () => openRun(episode.path),
      })]),
      el('td', { text: episode.pressure }),
      el('td', { text: episode.seed }),
      el('td', { class: episode.complete ? '' : 'bad', text: `${episode.rounds_written}/${episode.rounds_planned}` }),
    ]))),
  ])]));
}

/* A round in the strip is a moment worth watching, so clicking one opens the
 * floor there rather than making someone find it with the scrubber. */
function openOnFloor(_episodeId, roundIndex) {
  if (!state.run) return;
  showTab('floor');
  const start = () => {
    floor.view.goToRound(roundIndex);
    floor.view.play();
  };
  if (floor.path === state.run && floor.scene) start();
  else loadScene(state.run).then(() => { if (floor.scene) start(); });
}

/* Jumps the launch panel to a command with one field already filled in, so a
 * run you are looking at is one click from being analyzed. */
function prefill(commandName, fields) {
  const command = state.commands.find((item) => item.name === commandName);
  if (!command) return;
  selectCommand(commandName);
  for (const [name, value] of Object.entries(fields)) setValue(command, name, value);
  renderForm();
  document.getElementById('column-launch').scrollTo({ top: 0 });
  toast(`Loaded ${command.label} for ${Object.values(fields)[0]}`);
}

const legendKey = (color, text) => el('span', {}, [el('i', { style: `background:${color}` }), text]);
const fixed = (value) => (value == null ? '-' : Number(value).toFixed(3));
const percent = (value) => `${(value * 100).toFixed(1)}%`;

/* ------------------------------------------------------------ trading floor */

const floor = {
  view: null,
  scene: null,
  path: null,      // run whose scene is loaded
  wanted: null,    // run the user has selected, loaded on demand
  tab: 'console',
  following: false,
  // Where a link asked to start. Captured once at boot, because the first
  // render writes the hash back and would otherwise overwrite the request
  // before anything got round to honouring it.
  pending: null,
};

function ensureFloor() {
  if (!floor.view) {
    floor.view = new FloorView($('stage'));
    floor.view.onChange = renderFloorChrome;
  }
  return floor.view;
}

function showTab(name) {
  floor.tab = name;
  $('tab-console').setAttribute('aria-selected', String(name === 'console'));
  $('tab-floor').setAttribute('aria-selected', String(name === 'floor'));
  $('view-console').hidden = name !== 'console';
  $('view-floor').hidden = name !== 'floor';
  if (name === 'floor') {
    ensureFloor().resize();
    // The scene is fetched only once the floor is actually looked at. It reads
    // calls.jsonl, which is the largest file in a run directory, and most
    // sessions never open this tab at all.
    if (floor.wanted && floor.wanted !== floor.path) loadScene(floor.wanted);
  }
}

async function loadScene(path) {
  const view = ensureFloor();
  $('floor-empty').hidden = true;
  try {
    const scene = await api(`/api/scene?path=${encodeURIComponent(path)}`);
    floor.scene = scene;
    floor.path = path;
    view.load(scene);
    const wanted = floor.pending;
    floor.pending = null;
    if (wanted && wanted.round) {
      view.goToRound(wanted.round - 1);
      if (wanted.beat && wanted.beat > 1) {
        view.beatIndex = Math.min(wanted.beat - 1, Math.max(0, view.beats.length - 1));
        view.beatClock = 0;
        view.applyBeat();
      }
    }
    renderFloorChrome(view);
  } catch (error) {
    floor.scene = null;
    floor.path = null;
    $('floor-empty').hidden = false;
    $('floor-empty').textContent = String(error.message || error);
  }
}

function renderFloorChrome(view) {
  const scene = view.scene;
  if (scene && floor.tab === 'floor') writeHash();
  $('floor-empty').hidden = !!scene;
  if (!scene) { $('phase-rail').replaceChildren(); $('floor-hud').replaceChildren(); return; }

  $('floor-play').textContent = view.playing ? 'Pause' : 'Play';
  const round = view.round;
  $('floor-round').replaceChildren(
    el('span', { html: `round <strong>${round ? round.round : '-'}</strong> / ${scene.rounds.length}` }),
    document.createTextNode(`  ·  beat ${view.beatIndex + 1}/${view.beats.length}`),
    document.createTextNode(`  ·  setup ${scene.setup}, pressure ${scene.pressure}`),
  );

  // Phase rail: which of the six phases of this round have played.
  const beat = view.beat;
  const played = new Set(view.beats.slice(0, view.beatIndex + 1).map((item) => item.phase));
  const rail = $('phase-rail');
  rail.replaceChildren();
  for (const phase of scene.phases) {
    const isNow = beat && beat.phase === phase.id;
    const node = el('button', {
      type: 'button',
      class: isNow ? 'now' : (played.has(phase.id) ? 'done' : ''),
      title: phase.note,
      text: phase.label,
      onclick: () => {
        const index = view.beats.findIndex((item) => item.phase === phase.id);
        if (index >= 0) { view.beatIndex = index; view.beatClock = 0; view.applyBeat(); view.emit(); }
      },
    });
    if (isNow) node.style.color = ({
      brief: '#6030ff', signal: '#3794ff', share: '#cca700',
      trade: '#89d185', report: '#ff8d14', market: '#d14249',
    })[phase.id];
    rail.append(node);
  }

  renderFloorHud(view);
}

const SWATCH = { ken_griffin: '#6030ff', boss_1: '#3794ff', trader_a: '#ff8d14', trader_b: '#89d185' };

function renderFloorHud(view) {
  const round = view.round;
  const box = $('floor-hud');
  box.replaceChildren();
  if (!round) return;

  // Pre-round state until the market beat plays, post-round after it. Showing
  // the post-round budget during the share phase would put a number on screen
  // that the trader deciding to share could not have known.
  const beat = view.beat;
  const settled = beat && beat.phase === 'market';
  const states = (settled ? round.post_states : round.pre_states) || [];
  const budgets = states.map((state) => state.budget || 0);
  const widest = Math.max(0.001, ...budgets);

  for (const state of states) {
    const share = (state.budget || 0) / widest;
    const card = el('div', { class: `hud-card${(state.budget || 0) < 0.05 ? ' starved' : ''}` }, [
      el('div', { class: 'hud-name' }, [
        el('span', { class: 'swatch', style: `background:${SWATCH[state.trader_id] || '#fff'}` }),
        view.actorName(state.trader_id),
        el('span', { class: 'rank', text: `rank ${state.rank}` }),
      ]),
      el('div', { class: 'hud-bar' }, [el('i', { style: `width:${Math.max(2, share * 100)}%` })]),
      el('div', { class: 'hud-row' }, ['budget', el('b', { text: (state.budget || 0).toFixed(3) })]),
      el('div', { class: 'hud-row' }, ['book', el('b', { text: (state.cumulative_pnl || 0).toFixed(3) })]),
      el('div', { class: 'hud-row' }, ['behind by', el('b', { text: (state.pnl_gap || 0).toFixed(3) })]),
    ]);
    box.append(card);
  }
}

/* Follow-live: a running pilot appends rounds to the same file the scene was
 * built from, so re-fetching while it runs turns the floor into a live view of
 * an episode in progress rather than a replay of a finished one. */
async function followLiveEpisode() {
  if (!floor.following || floor.tab !== 'floor') return;
  const job = state.jobs.find((item) => item.status === 'running' && item.run_directory);
  if (!job) return;
  if (job.run_directory !== floor.path) {
    floor.wanted = job.run_directory;
    await loadScene(job.run_directory);
    return;
  }
  try {
    const scene = await api(`/api/scene?path=${encodeURIComponent(floor.path)}`);
    if (scene.rounds.length !== (floor.scene ? floor.scene.rounds.length : 0)) {
      floor.scene = scene;
      ensureFloor().load(scene);
    }
  } catch (_) { /* the next poll retries */ }
}

$('tab-console').addEventListener('click', () => { showTab('console'); writeHash(); });
$('tab-floor').addEventListener('click', () => { showTab('floor'); writeHash(); });
$('floor-play').addEventListener('click', () => ensureFloor().toggle());
$('floor-next').addEventListener('click', () => { ensureFloor().pause(); floor.view.step(1); });
$('floor-back').addEventListener('click', () => { ensureFloor().pause(); floor.view.step(-1); });
$('floor-speed').addEventListener('change', (event) => { ensureFloor().speed = Number(event.target.value); });
$('floor-follow').addEventListener('change', (event) => { floor.following = event.target.checked; followLiveEpisode(); });

document.addEventListener('keydown', (event) => {
  if (floor.tab !== 'floor' || !floor.scene) return;
  const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (typing) return;
  if (event.key === ' ') { event.preventDefault(); ensureFloor().toggle(); }
  else if (event.key === 'ArrowRight') { event.preventDefault(); ensureFloor().pause(); floor.view.step(1); }
  else if (event.key === 'ArrowLeft') { event.preventDefault(); ensureFloor().pause(); floor.view.step(-1); }
});

/* ------------------------------------------------------------------- poll */

let timer = null;

async function tick() {
  try {
    if (state.job) {
      const payload = await api(`/api/jobs/${state.job}/log?offset=${state.logOffset}`);
      state.jobs = await api('/api/jobs');
      if (state.logSeen !== state.job) {
        $('console').replaceChildren();
        state.logSeen = state.job;
        if (payload.dropped) {
          appendLines([`... ${payload.dropped} earlier lines dropped (log capped) ...`]);
        }
      }
      if (payload.lines.length) appendLines(payload.lines);
      state.logOffset = payload.next_offset;
      renderConsoleBar(payload.job);
    } else {
      state.jobs = await api('/api/jobs');
      renderConsoleBar(null);
    }
    renderJobs();
    await refreshRunsIfJobFinished();
    await followLiveEpisode();
  } catch (error) {
    // A desk whose server has gone away should say so once, not every second.
    if (!document.body.dataset.offline) {
      document.body.dataset.offline = '1';
      toast(`Lost the desk server: ${error.message || error}`, 'bad');
    }
    schedule();
    return;
  }
  delete document.body.dataset.offline;
  schedule();
}

// A finished pilot or sweep has just written a directory the Runs panel does
// not know about. Watching for the transition is what keeps a fresh run from
// needing a manual Refresh to become selectable.
let lastStatuses = {};

async function refreshRunsIfJobFinished() {
  const now = {};
  let finishedOne = false;
  for (const job of state.jobs) {
    now[job.id] = job.status;
    const before = lastStatuses[job.id];
    if (before && before !== job.status && !['running', 'queued'].includes(job.status)) {
      finishedOne = true;
    }
  }
  lastStatuses = now;
  if (!finishedOne) return;
  try {
    state.runs = await api('/api/runs');
    renderRuns();
    renderForm();
  } catch (_) { /* the next poll will try again */ }
}

// Poll fast while something is running and slowly when nothing is, so an idle
// tab is not making a request a second for no reason.
function schedule() {
  clearTimeout(timer);
  const busy = state.jobs.some((job) => job.status === 'running' || job.status === 'queued');
  timer = setTimeout(tick, busy ? 800 : 4000);
}

async function refresh() {
  const payload = await api('/api/state');
  state.commands = payload.commands;
  state.environment = payload.environment;
  state.runs = payload.runs;
  state.jobs = payload.jobs;
  if (!state.command || !state.commands.some((item) => item.name === state.command)) {
    state.command = localStorage.getItem('desk.command') || state.commands[0].name;
    if (!state.commands.some((item) => item.name === state.command)) state.command = state.commands[0].name;
  }
  // A reload should not lose the console. Jobs outlive the page -- they are
  // processes, not tab state -- so the newest one is worth reopening, and a
  // still-running sweep is exactly what someone reloading wants to see.
  if (!state.job && state.jobs.length) {
    const running = [...state.jobs].reverse().find((job) => job.status === 'running');
    state.job = (running || state.jobs[state.jobs.length - 1]).id;
    state.logOffset = 0;
    state.logSeen = null;
  }

  renderEnvironment();
  renderCommands();
  renderForm();
  renderRuns();
  renderJobs();
}

/* ------------------------------------------------------------------- boot */

$('launch').addEventListener('click', launch);
$('refresh').addEventListener('click', () => refresh().then(() => toast('Reloaded', 'ok')));
$('run-filter').addEventListener('input', (event) => { state.filter = event.target.value; renderRuns(); });
$('stop-job').addEventListener('click', async () => {
  if (!state.job) return;
  try {
    await api(`/api/jobs/${state.job}/stop`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    toast('Stop signalled to the process group', 'ok');
    tick();
  } catch (error) { toast(String(error.message || error), 'bad'); }
});
$('clear-jobs').addEventListener('click', async () => {
  await api('/api/jobs/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  state.job = null;
  state.logSeen = null;
  $('console').replaceChildren();
  tick();
});

// Enter launches from anywhere in the form; a form of steppers and toggles has
// no natural submit target otherwise.
$('params').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') { event.preventDefault(); launch(); }
});

/* The hash carries what is on screen: which run is open and which tab is
 * showing it. That makes "watch p3-s1001 on the floor" a link someone can
 * paste, which is the whole reason to have it. */
function hashState() {
  const parsed = new URLSearchParams(location.hash.slice(1));
  const number = (key) => (parsed.get(key) === null ? null : Number(parsed.get(key)));
  return { run: parsed.get('run'), tab: parsed.get('tab'), round: number('round'), beat: number('beat') };
}

function writeHash() {
  const parsed = new URLSearchParams();
  if (state.run) parsed.set('run', state.run);
  if (floor.tab === 'floor') {
    parsed.set('tab', 'floor');
    // The moment, not just the episode. "Round 7, where it withheld" is the
    // thing worth sending someone, and it is one line to make it a link.
    if (floor.view && floor.scene) {
      parsed.set('round', String(floor.view.roundIndex + 1));
      parsed.set('beat', String(floor.view.beatIndex + 1));
    }
  }
  const next = `#${parsed.toString()}`;
  if (next !== location.hash) history.replaceState(null, '', next || '#');
}

window.addEventListener('hashchange', () => {
  const wanted = hashState();
  if (wanted.run && wanted.run !== state.run) {
    if (wanted.round) floor.pending = { round: wanted.round, beat: wanted.beat };
    if (wanted.tab && wanted.tab !== floor.tab) showTab(wanted.tab);
    openRun(wanted.run, { push: false });
    return;
  }
  if (wanted.tab && wanted.tab !== floor.tab) showTab(wanted.tab);
});

refresh()
  .then(() => {
    const wanted = hashState();
    if (wanted.round) floor.pending = { round: wanted.round, beat: wanted.beat };
    if (wanted.tab === 'floor') showTab('floor');
    return wanted.run ? openRun(wanted.run, { push: false }) : null;
  })
  .then(tick)
  .catch((error) => {
    document.getElementById('columns').prepend(
      el('div', { class: 'form-error', text: `Could not reach the desk server: ${error.message || error}` }));
  });
