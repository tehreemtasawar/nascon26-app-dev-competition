import express from 'express';
import crypto from 'crypto';

const app = express();
const SALT = process.env.DAY1_SALT || '';
const ID = /^[A-Za-z0-9_.:-]{1,64}$/;
const TIE_BREAKS = ['h2h_points', 'h2h_diff', 'overall_diff', 'scored', 'fair_play', 'draw_lots'];
const nowUtc = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
const clone = value => JSON.parse(JSON.stringify(value));
const canonical = value => Array.isArray(value) ? `[${value.map(canonical).join(',')}]`
  : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`
    : JSON.stringify(value);
const sign = (id, payload) => crypto.createHmac('sha256', Buffer.from(SALT, 'utf8'))
  .update(`${id}|${canonical(payload)}`).digest('hex');
const fail = (res, status, code, message, details = {}) =>
  res.status(status).json({ error: { code, message, details } });
const validation = (res, fields) => fail(res, 400, 'VALIDATION_ERROR', 'Invalid request', { fields });

const sports = new Map();
const matches = new Map();
const leagues = new Map();
const orders = new Map();
const rosters = new Map();
const processedActions = new Map();
const subscribers = new Map();
let store = { stock: {}, reserved: {}, payment: 0, seed: 42 };
let resetState = {};

const seedSports = () => [
  ['football', { sport_id: 'football', name: 'Football', scoring_model: 'event', periods: { count: 2, duration_minutes: 45 }, scoring_events: { goal: { points: 1 } }, draw_allowed: true, overtime: { policy: 'none' }, tie_break_order: TIE_BREAKS, roster: { min_squad_size: 11, max_squad_size: 25, required_positions: { gk: 1 } } }],
  ['basketball', { sport_id: 'basketball', name: 'Basketball', scoring_model: 'event', periods: { count: 4, duration_minutes: 12 }, scoring_events: { free_throw: { points: 1 }, two_pointer: { points: 2 }, three_pointer: { points: 3 } }, draw_allowed: false, overtime: { policy: 'extra_time', duration_minutes: 5 }, tie_break_order: TIE_BREAKS, roster: { min_squad_size: 5, max_squad_size: 15, required_positions: {} } }],
  ['cricket', { sport_id: 'cricket', name: 'Cricket', scoring_model: 'innings', periods: { innings_per_team: 1, overs_per_innings: 20, balls_per_over: 6, wickets_per_innings: 10 }, scoring_events: { dot_ball: { runs: 0, legal_ball: true, wicket: false }, single: { runs: 1, legal_ball: true, wicket: false }, two: { runs: 2, legal_ball: true, wicket: false }, four: { runs: 4, legal_ball: true, wicket: false }, six: { runs: 6, legal_ball: true, wicket: false }, wide: { runs: 1, legal_ball: false, wicket: false }, no_ball: { runs: 1, legal_ball: false, wicket: false }, wicket: { runs: 0, legal_ball: true, wicket: true } }, draw_allowed: true, overtime: { policy: 'super_over' }, tie_break_order: TIE_BREAKS, roster: { min_squad_size: 11, max_squad_size: 18, required_positions: { wicketkeeper: 1 } } }],
  ['esports', { sport_id: 'esports', name: 'Esports', scoring_model: 'round', periods: { best_of: 3 }, scoring_events: { round_win: { rounds: 1 } }, draw_allowed: false, overtime: { policy: 'none' }, tie_break_order: TIE_BREAKS, roster: { min_squad_size: 5, max_squad_size: 8, required_positions: {} } }]
].forEach(([id, config]) => sports.set(id, config));

function reset(body = {}) {
  sports.clear();
  seedSports();
  matches.clear(); leagues.clear(); orders.clear(); rosters.clear(); processedActions.clear();
  const stock = { 'var-jersey-001-M': 1, 'var-jersey-001-L': 5, ...(body.stock || {}) };
  store = { stock, reserved: Object.fromEntries(Object.keys(stock).map(k => [k, 0])), payment: 0, seed: Number.isInteger(body.seed) ? body.seed : 42 };
  resetState = { tenants: ['tenant-alpha', 'tenant-beta'], users: new Map([
    ['admin@nascon.test', { role: 'super_admin', tenant_id: null }],
    ['organizer@nascon.test', { role: 'organizer', tenant_id: 'tenant-alpha', league_id: 'league-alpha-1' }],
    ['manager@nascon.test', { role: 'manager', tenant_id: 'tenant-alpha', club_id: 'club-alpha-1' }],
    ['player@nascon.test', { role: 'player', tenant_id: 'tenant-alpha', player_id: 'player-alpha-1' }],
    ['viewer@nascon.test', { role: 'viewer', tenant_id: null }]
  ]), leagues: new Map([
    ['league-alpha-1', { tenant_id: 'tenant-alpha', owner: 'organizer@nascon.test' }],
    ['league-alpha-2', { tenant_id: 'tenant-alpha', owner: null }],
    ['league-beta-1', { tenant_id: 'tenant-beta', owner: null }]
  ]), clubs: new Map([
    ['club-alpha-1', { tenant_id: 'tenant-alpha', owner: 'manager@nascon.test' }],
    ['club-alpha-2', { tenant_id: 'tenant-alpha', owner: null }],
    ['club-beta-1', { tenant_id: 'tenant-beta', owner: null }]
  ]), players: new Map([
    ['player-alpha-1', { tenant_id: 'tenant-alpha', club_id: 'club-alpha-1', owner: 'player@nascon.test' }],
    ['player-alpha-2', { tenant_id: 'tenant-alpha', club_id: 'club-alpha-2', owner: null }],
    ['player-beta-1', { tenant_id: 'tenant-beta', club_id: 'club-beta-1', owner: null }]
  ]) };
}
reset();

function tokenFor(claims) {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({ ...claims, iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url');
  const content = `${header}.${payload}`;
  return `${content}.${crypto.createHmac('sha256', SALT).update(content).digest('base64url')}`;
}
function verifyToken(value) {
  const parts = String(value || '').replace(/^Bearer\s+/, '').split('.');
  if (parts.length !== 3) return null;
  const [header, payload, signature] = parts;
  let decoded;
  try {
    decoded = { header: JSON.parse(Buffer.from(header, 'base64url').toString()), payload: JSON.parse(Buffer.from(payload, 'base64url').toString()) };
  } catch { return null; }
  if (decoded.header.alg !== 'HS256' || decoded.header.typ !== 'JWT' || decoded.payload.exp < Math.floor(Date.now() / 1000)) return null;
  const expected = crypto.createHmac('sha256', SALT).update(`${header}.${payload}`).digest('base64url');
  if (signature.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) return null;
  return decoded.payload;
}

app.use(express.json({ limit: '1mb' }));
app.get('/health', (_, res) => res.json({ status: 'ok' }));
app.post('/audit/v1/reset', (req, res) => {
  reset(req.body || {});
  res.json({ status: 'reset_complete', seed: store.seed, sports: [...sports.keys()], tenants: resetState.tenants, stock: store.stock });
});

function validSport(body, res) {
  const bad = [];
  if (typeof body.sport_id !== 'string' || !/^[a-z0-9_-]{2,40}$/.test(body.sport_id)) bad.push('sport_id');
  if (typeof body.name !== 'string' || body.name.length < 1 || body.name.length > 80) bad.push('name');
  if (!['event', 'innings', 'round'].includes(body.scoring_model)) bad.push('scoring_model');
  const p = body.periods;
  if (!p || typeof p !== 'object' || Array.isArray(p)) bad.push('periods');
  else if ((body.scoring_model === 'event' && !(Number.isInteger(p.count) && p.count > 0 && Number.isInteger(p.duration_minutes) && p.duration_minutes > 0))
    || (body.scoring_model === 'innings' && !['innings_per_team', 'overs_per_innings', 'balls_per_over', 'wickets_per_innings'].every(k => Number.isInteger(p[k]) && p[k] > 0))
    || (body.scoring_model === 'round' && !(Number.isInteger(p.best_of) && p.best_of > 0 && p.best_of % 2 === 1))) bad.push('periods');
  const events = body.scoring_events;
  if (!events || typeof events !== 'object' || !Object.keys(events).length) bad.push('scoring_events');
  else for (const [key, value] of Object.entries(events)) {
    const valid = /^[a-z0-9_]{1,40}$/.test(key) && value && typeof value === 'object'
      && (body.scoring_model === 'event' ? Number.isInteger(value.points) && value.points >= 1
        : body.scoring_model === 'innings' ? Number.isInteger(value.runs) && value.runs >= 0 && typeof value.legal_ball === 'boolean' && typeof value.wicket === 'boolean'
          : Number.isInteger(value.rounds) && value.rounds >= 1);
    if (!valid) { bad.push('scoring_events'); break; }
  }
  if (typeof body.draw_allowed !== 'boolean') bad.push('draw_allowed');
  if (!body.overtime || !['none', 'extra_time', 'shootout', 'golden_score', 'super_over'].includes(body.overtime.policy)) bad.push('overtime');
  const roster = body.roster;
  if (!roster || !Number.isInteger(roster.min_squad_size) || !Number.isInteger(roster.max_squad_size) || roster.min_squad_size < 1 || roster.min_squad_size > roster.max_squad_size || !roster.required_positions || typeof roster.required_positions !== 'object') bad.push('roster');
  if (bad.length) validation(res, [...new Set(bad)]);
  return bad.length === 0;
}
app.post('/audit/v1/sports', (req, res) => {
  if (!validSport(req.body, res)) return;
  if (sports.has(req.body.sport_id)) return fail(res, 409, 'SPORT_EXISTS', 'Sport exists', { sport_id: req.body.sport_id });
  const config = { ...req.body, tie_break_order: req.body.tie_break_order || TIE_BREAKS };
  sports.set(config.sport_id, config);
  res.status(201).json({ sport_id: config.sport_id, status: 'created', config });
});

function circleSchedule(teams, legs) {
  const list = [...teams]; if (list.length % 2) list.push(null);
  const rounds = list.length - 1, result = [];
  for (let leg = 1; leg <= legs; leg++) {
    let current = [...list];
    for (let round = 1; round <= rounds; round++) {
      const games = [];
      for (let i = 0; i < current.length / 2; i++) {
        const a = current[i], b = current[current.length - 1 - i];
        if (a && b) {
          const home = (round + leg) % 2 ? a : b;
          games.push({ match_id: `RR-L${leg}-R${(leg - 1) * rounds + round}-M${games.length + 1}`, leg, home, away: home === a ? b : a, status: 'scheduled', awarded_to: null });
        }
      }
      result.push({ round: (leg - 1) * rounds + round, matches: games, byes: current.filter(x => x && !games.some(g => g.home === x || g.away === x)) });
      current = [current[0], current[current.length - 1], ...current.slice(1, -1)];
    }
  }
  return result;
}
function nextPower(n) { let x = 1; while (x < n) x *= 2; return x; }
function bracketOrder(size) { if (size === 2) return [1, 2]; const half = bracketOrder(size / 2); return half.flatMap(s => [s, size + 1 - s]); }
function pairBacktracking(items, used, pairs = []) {
  if (!items.length) return pairs;
  const first = items[0];
  for (let i = 1; i < items.length; i++) {
    const second = items[i], key = [first, second].sort().join('|');
    if (!used.has(key)) {
      const found = pairBacktracking(items.slice(1, i).concat(items.slice(i + 1)), new Set([...used, key]), [...pairs, [first, second]]);
      if (found) return found;
    }
  }
  return null;
}
app.post('/audit/v1/fixtures', (req, res) => {
  const { format, teams = [], params = {} } = req.body || {};
  const limits = { round_robin: [2, 40], swiss: [2, 64], single_elim: [2, 128], double_elim: [3, 128] };
  if (!limits[format] || !Array.isArray(teams) || teams.length < limits[format][0] || teams.length > limits[format][1] || new Set(teams).size !== teams.length) return validation(res, ['format', 'teams']);
  if (format === 'round_robin') {
    const legs = params.legs || 1; if (![1, 2].includes(legs)) return validation(res, ['params.legs']);
    const rounds = circleSchedule(teams, legs);
    const withdrawals = params.withdrawals || [], policy = params.withdrawal_policy || 'forfeit_remaining';
    for (const w of withdrawals) {
      if (!teams.includes(w.team_id) || !Number.isInteger(w.after_round) || w.after_round < 0 || w.after_round > rounds.length) return validation(res, ['params.withdrawals']);
      for (const round of rounds) for (const match of round.matches) if (match.home === w.team_id || match.away === w.team_id) {
        if (policy === 'void_all' || round.round > w.after_round) { match.status = policy === 'void_all' ? 'voided' : 'forfeit'; match.awarded_to = policy === 'void_all' ? null : (match.home === w.team_id ? match.away : match.home); }
      }
    }
    const all = rounds.flatMap(x => x.matches);
    return res.json({ format, legs, team_count: teams.length, round_count: rounds.length, rounds, summary: { total: all.length, scheduled: all.filter(x => x.status === 'scheduled').length, forfeit: all.filter(x => x.status === 'forfeit').length, voided: all.filter(x => x.status === 'voided').length } });
  }
  if (format === 'single_elim') {
    const size = nextPower(teams.length), order = bracketOrder(size), rounds = [];
    let current = order.map(seed => seed <= teams.length ? teams[seed - 1] : null);
    let round = 1;
    while (current.length > 1) {
      const matchesInRound = [];
      for (let i = 0; i < current.length; i += 2) matchesInRound.push({ match_id: `R${round}M${i / 2 + 1}`, home: current[i], away: current[i + 1], bye: !current[i] || !current[i + 1], winner: current[i] && !current[i + 1] ? current[i] : current[i + 1] && !current[i] ? current[i + 1] : null });
      rounds.push({ round, matches: matchesInRound }); current = matchesInRound.map(x => x.winner); round++;
    }
    return res.json({ format, bracket_size: size, rounds, third_place_match: Boolean(params.third_place_match) });
  }
  if (format === 'swiss') {
    const total = params.total_rounds || Math.ceil(Math.log2(teams.length)), currentRound = params.round || 1, history = params.history || [];
    if (!Number.isInteger(total) || total < 1 || total > teams.length - 1 || currentRound < 1 || currentRound > total || history.length !== currentRound - 1) return validation(res, ['params']);
    const scores = Object.fromEntries(teams.map(t => [t, 0])), byes = new Set(), used = new Set();
    for (const h of history) { if (h.bye) { scores[h.bye] += 1; byes.add(h.bye); } for (const m of h.matches || []) { const key = [m.home, m.away].sort().join('|'); used.add(key); if (m.result === 'home') scores[m.home] += 1; else if (m.result === 'away') scores[m.away] += 1; else scores[m.home] += .5; scores[m.away] += .5; } }
    const ordered = [...teams].sort((a, b) => scores[b] - scores[a] || teams.indexOf(a) - teams.indexOf(b));
    let bye = null, candidates = ordered.filter(t => !byes.has(t));
    if (teams.length % 2) { bye = candidates[candidates.length - 1] || ordered[ordered.length - 1]; candidates = candidates.filter(t => t !== bye); }
    let pairs = pairBacktracking(candidates, used);
    if (!pairs) return fail(res, 409, 'NO_VALID_PAIRING', 'No valid pairing', { round: currentRound });
    const standings = ordered.map((team, i) => ({ rank: i + 1, team_id: team, score: scores[team], buchholz: 0 }));
    return res.json({ format, round: currentRound, total_rounds: total, pairings: pairs.map((p, i) => ({ match_id: `SW-R${currentRound}-M${i + 1}`, home: p[0], away: p[1] })), bye, standings });
  }
  const size = nextPower(teams.length);
  return res.json({ format, bracket_size: size, rounds: [{ round: 1, matches: teams.slice(0, -1).map((team, i) => ({ match_id: `WB-R1-M${i + 1}`, home: team, away: teams[i + 1] })) }], grand_final: { gf1: { match_id: 'GF1', conditional: false }, gf2: { match_id: 'GF2', conditional: true, required: false } } });
});

const activeEvents = match => {
  const compensated = new Set(match.events.filter(e => e.type === 'compensation').map(e => e.payload.compensates));
  return match.events.filter(e => e.type !== 'compensation' && !compensated.has(e.event_id));
};
function project(match) {
  const sport = sports.get(match.sport_id), events = activeEvents(match);
  const side = team_id => ({ team_id, score: 0, wickets: sport.scoring_model === 'innings' ? 0 : null, balls: sport.scoring_model === 'innings' ? 0 : null, overs: null, fair_play: 0 });
  const home = side(match.home), away = side(match.away), byTeam = { [match.home]: home, [match.away]: away };
  let status = 'upcoming', tie = null;
  for (const event of match.events) { if (event.type === 'match_start') status = 'in_progress'; if (event.type === 'match_end') status = 'completed'; if (event.type === 'tiebreak_winner') tie = event.payload.team_id; }
  for (const event of events) { const p = event.payload, target = byTeam[p.team_id]; if (event.type === 'discipline') target.fair_play += p.points; else if (event.type === 'tiebreak_winner') tie = p.team_id; else if (event.type === 'score') { const rule = sport.scoring_events[p.event_type]; if (sport.scoring_model === 'event') target.score += rule.points; else if (sport.scoring_model === 'round') target.score += rule.rounds; else { target.score += rule.runs; if (rule.legal_ball) target.balls++; if (rule.wicket) target.wickets++; } } }
  if (sport.scoring_model === 'innings') for (const t of [home, away]) t.overs = `${Math.floor(t.balls / sport.periods.balls_per_over)}.${t.balls % sport.periods.balls_per_over}`;
  const winner = home.score > away.score ? match.home : away.score > home.score ? match.away : tie;
  const outcome = status !== 'completed' ? 'pending' : home.score !== away.score ? (home.score > away.score ? 'home_win' : 'away_win') : tie ? (tie === match.home ? 'home_win' : 'away_win') : sport.draw_allowed ? 'draw' : 'undecided';
  const compensated = new Set(match.events.filter(e => e.type === 'compensation').map(e => e.payload.compensates));
  return { match_id: match.match_id, sport_id: match.sport_id, league_id: match.league_id || null, status, outcome, winner_team_id: winner || null, tiebreak_winner_team_id: tie, home, away, version: match.events.length, events: match.events.map((e, i) => ({ sequence: i + 1, event_id: e.event_id, type: e.type, payload: e.payload, signature: e.signature, compensated: compensated.has(e.event_id), compensated_by: match.events.find(x => x.type === 'compensation' && x.payload.compensates === e.event_id)?.event_id || null })) };
}
function eventResponse(event, match, status = 201) { return { status, body: { event_id: event.event_id, match_id: event.match_id, type: event.type, sequence: match.events.length, match_version: match.events.length, signature: event.signature } }; }
function publish(match) {
  const listeners = subscribers.get(match.match_id) || [];
  const message = `event: score\ndata: ${JSON.stringify(project(match))}\n\n`;
  for (const response of listeners) response.write(message);
}
app.post('/audit/v1/events', (req, res) => {
  const b = req.body || {}, bad = [];
  if (typeof b.event_id !== 'string' || !ID.test(b.event_id)) bad.push('event_id');
  if (typeof b.match_id !== 'string' || !ID.test(b.match_id)) bad.push('match_id');
  if (typeof b.type !== 'string') bad.push('type');
  if (!b.payload || typeof b.payload !== 'object' || Array.isArray(b.payload)) bad.push('payload');
  if (bad.length) return validation(res, bad);
  for (const match of matches.values()) { const old = match.events.find(e => e.event_id === b.event_id); if (old) return canonical(old.payload) === canonical(b.payload) && old.type === b.type && old.match_id === b.match_id ? res.status(200).json(eventResponse(old, match, 200).body) : fail(res, 409, 'DUPLICATE_EVENT_ID', 'event_id reused', {}); }
  let match = matches.get(b.match_id), p = b.payload;
  if (b.type === 'match_init') {
    if (match) return fail(res, 409, 'MATCH_EXISTS', 'Match exists', {});
    if (typeof p.sport_id !== 'string' || typeof p.home_team_id !== 'string' || typeof p.away_team_id !== 'string') return validation(res, ['payload']);
    if (!sports.has(p.sport_id)) return fail(res, 404, 'SPORT_NOT_FOUND', 'Sport not found', {});
    match = { match_id: b.match_id, sport_id: p.sport_id, home: p.home_team_id, away: p.away_team_id, league_id: p.league_id || null, events: [] }; matches.set(b.match_id, match);
  } else {
    if (!match) return fail(res, 404, 'MATCH_NOT_FOUND', 'Match not found', {});
    const view = project(match), sport = sports.get(match.sport_id);
    if (['match_start', 'score', 'discipline', 'tiebreak_winner'].includes(b.type) && view.status !== 'in_progress' && b.type !== 'match_start') return fail(res, 409, 'MATCH_NOT_IN_PROGRESS', 'Match not in progress', {});
    if (b.type === 'match_start' && view.status !== 'upcoming') return fail(res, 409, 'ILLEGAL_TRANSITION', 'Illegal transition', {});
    if (b.type === 'score') {
      if (![match.home, match.away].includes(p.team_id)) return validation(res, ['payload.team_id']);
      if (!Object.hasOwn(sport.scoring_events, p.event_type)) return fail(res, 400, 'UNKNOWN_EVENT_TYPE', 'Unknown event type', { event_type: p.event_type });
      const t = p.team_id === match.home ? view.home : view.away;
      if (sport.scoring_model === 'innings' && (t.balls >= sport.periods.innings_per_team * sport.periods.overs_per_innings * sport.periods.balls_per_over || t.wickets >= sport.periods.innings_per_team * sport.periods.wickets_per_innings)) return fail(res, 409, 'INNINGS_COMPLETE', 'Innings complete', {});
      if (sport.scoring_model === 'round' && t.score >= (sport.periods.best_of + 1) / 2) return fail(res, 409, 'SERIES_ALREADY_DECIDED', 'Series decided', {});
    } else if (b.type === 'discipline' && (![match.home, match.away].includes(p.team_id) || !Number.isInteger(p.points))) return validation(res, ['payload']);
    else if (b.type === 'tiebreak_winner' && ![match.home, match.away].includes(p.team_id)) return validation(res, ['payload.team_id']);
    else if (b.type === 'match_end') { if (view.status !== 'in_progress') return fail(res, 409, 'ILLEGAL_TRANSITION', 'Illegal transition', {}); if (view.home.score === view.away.score && !sport.draw_allowed && !view.tiebreak_winner_team_id) return fail(res, 409, 'TIE_NOT_ALLOWED', 'Tie not allowed', {}); }
    else if (b.type === 'compensation') { const target = match.events.find(e => e.event_id === p.compensates); if (!target) return fail(res, 404, 'EVENT_NOT_FOUND', 'Event not found', {}); if (!['score', 'discipline', 'tiebreak_winner'].includes(target.type) || match.events.some(e => e.type === 'compensation' && e.payload.compensates === target.event_id)) return fail(res, 409, 'INVALID_COMPENSATION', 'Invalid compensation', {}); }
    else if (!['match_start', 'match_end'].includes(b.type)) return validation(res, ['type']);
  }
  const event = { event_id: b.event_id, match_id: b.match_id, type: b.type, payload: clone(p), signature: sign(b.event_id, p) }; match.events.push(event);
  publish(match);
  const result = eventResponse(event, match); res.status(result.status).json(result.body);
});
app.get('/audit/v1/score/:id', (req, res) => { const match = matches.get(req.params.id); return match ? res.json(project(match)) : fail(res, 404, 'MATCH_NOT_FOUND', 'Match not found', {}); });
app.get('/audit/v1/stream/:id', (req, res) => {
  const match = matches.get(req.params.id);
  if (!match) return fail(res, 404, 'MATCH_NOT_FOUND', 'Match not found', {});
  res.status(200).set({ 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
  res.write(`event: score\ndata: ${JSON.stringify(project(match))}\n\n`);
  const listeners = subscribers.get(match.match_id) || [];
  listeners.push(res); subscribers.set(match.match_id, listeners);
  req.on('close', () => subscribers.set(match.match_id, (subscribers.get(match.match_id) || []).filter(item => item !== res)));
});

app.post('/audit/v1/leagues', (req, res) => {
  const b = req.body || {}, bad = [];
  if (typeof b.league_id !== 'string' || !ID.test(b.league_id)) bad.push('league_id');
  if (typeof b.sport_id !== 'string') bad.push('sport_id');
  if (!Array.isArray(b.teams) || b.teams.length < 2 || new Set(b.teams).size !== b.teams.length) bad.push('teams');
  if (!Array.isArray(b.fixtures)) bad.push('fixtures');
  if (bad.length) return validation(res, bad);
  if (!sports.has(b.sport_id)) return fail(res, 404, 'SPORT_NOT_FOUND', 'Sport not found', {});
  if (leagues.has(b.league_id)) return fail(res, 409, 'LEAGUE_EXISTS', 'League exists', {});
  const fixtureIds = new Set();
  for (const f of b.fixtures) { if (!b.teams.includes(f.home) || !b.teams.includes(f.away) || f.home === f.away) return validation(res, ['fixtures']); if (fixtureIds.has(f.match_id) || matches.has(f.match_id)) return fail(res, 409, 'MATCH_EXISTS', 'Match exists', {}); fixtureIds.add(f.match_id); matches.set(f.match_id, { match_id: f.match_id, sport_id: b.sport_id, home: f.home, away: f.away, league_id: b.league_id, events: [{ event_id: `init-${f.match_id}`, match_id: f.match_id, type: 'match_init', payload: { sport_id: b.sport_id, home_team_id: f.home, away_team_id: f.away, league_id: b.league_id }, signature: sign(`init-${f.match_id}`, { sport_id: b.sport_id, home_team_id: f.home, away_team_id: f.away, league_id: b.league_id }) }] }); }
  leagues.set(b.league_id, { ...clone(b), points: b.points || { win: 3, draw: 1, loss: 0 }, tie_break_order: b.tie_break_order || TIE_BREAKS, qualification: b.qualification || { spots: b.teams.length } });
  res.status(201).json({ league_id: b.league_id, status: 'created', team_count: b.teams.length, fixture_count: b.fixtures.length });
});
app.get('/audit/v1/standings/:id', (req, res) => {
  const league = leagues.get(req.params.id); if (!league) return fail(res, 404, 'LEAGUE_NOT_FOUND', 'League not found', {});
  const sport = sports.get(league.sport_id), table = Object.fromEntries(league.teams.map(team => [team, { team_id: team, played: 0, won: 0, drawn: 0, lost: 0, scored: 0, conceded: 0, diff: 0, points: 0, fair_play: 0 }]));
  const completed = league.fixtures.map(f => matches.get(f.match_id)).filter(Boolean).map(project).filter(x => x.status === 'completed' && x.outcome !== 'undecided');
  const h2h = Object.fromEntries(league.teams.map(a => [a, Object.fromEntries(league.teams.filter(b => b !== a).map(b => [b, { played: 0, points: 0, scored: 0, conceded: 0 }]))]));
  for (const result of completed) { const h = table[result.home.team_id], a = table[result.away.team_id]; for (const [own, other] of [[h, a], [a, h]]) { own.played++; own.scored += own.team_id === result.home.team_id ? result.home.score : result.away.score; own.conceded += own.team_id === result.home.team_id ? result.away.score : result.home.score; own.fair_play += own.team_id === result.home.team_id ? result.home.fair_play : result.away.fair_play; } if (result.outcome === 'draw') { h.drawn++; a.drawn++; h.points += league.points.draw; a.points += league.points.draw; } else { const winner = result.winner_team_id === h.team_id ? h : a, loser = winner === h ? a : h; winner.won++; loser.lost++; winner.points += league.points.win; loser.points += league.points.loss; } h.diff = h.scored - h.conceded; a.diff = a.scored - a.conceded; h2h[h.team_id][a.team_id].played++; h2h[a.team_id][h.team_id].played++; h2h[h.team_id][a.team_id].scored += result.home.score; h2h[h.team_id][a.team_id].conceded += result.away.score; h2h[a.team_id][h.team_id].scored += result.away.score; h2h[a.team_id][h.team_id].conceded += result.home.score; }
  const rows = Object.values(table).sort((a, b) => b.points - a.points || b.diff - a.diff || b.scored - a.scored || a.team_id.localeCompare(b.team_id)).map((row, i, all) => ({ ...row, rank: i + 1, status: i < league.qualification.spots ? 'clinched' : 'still_possible', resolved_by: null }));
  res.json({ league_id: league.league_id, sport_id: league.sport_id, qualification_spots: league.qualification.spots, table: rows, h2h });
});

app.post('/audit/v1/roster/setup', (req, res) => { const b = req.body || {}; if (!b.league?.league_id || !Array.isArray(b.squads) || !Array.isArray(b.players)) return validation(res, ['league', 'squads', 'players']); const sport = sports.get(b.league.sport_id); rosters.set(b.league.league_id, { ...clone(b), max_squad_size: b.league.max_squad_size || sport?.roster.max_squad_size || 25, required_positions: b.league.required_positions || sport?.roster.required_positions || {}, audits: [], requests: new Map(), matches: b.matches_in_progress || [] }); res.status(201).json({ league_id: b.league.league_id, status: 'configured', squad_counts: Object.fromEntries(b.squads.map(s => [s.squad_id, b.players.filter(p => p.squad_id === s.squad_id).length])) }); });
app.post('/audit/v1/roster/transfer', (req, res) => {
  const b = req.body || {}, state = rosters.get(b.league_id); if (!state) return fail(res, 404, 'LEAGUE_NOT_FOUND', 'League not found', {});
  if (state.requests.has(b.request_id)) return res.status(200).json(state.requests.get(b.request_id));
  const player = state.players.find(p => p.player_id === b.player_id), from = state.squads.find(s => s.squad_id === b.from_squad_id), to = b.to_squad_id && state.squads.find(s => s.squad_id === b.to_squad_id);
  if (!player) return fail(res, 404, 'PLAYER_NOT_FOUND', 'Player not found', {}); if (!from || (b.to_squad_id && !to)) return fail(res, 404, 'SQUAD_NOT_FOUND', 'Squad not found', {});
  if (from.tenant_id !== state.league.tenant_id || (to && to.tenant_id !== state.league.tenant_id)) return fail(res, 409, 'CROSS_TENANT_TRANSFER', 'Cross tenant transfer', {});
  if (player.squad_id !== from.squad_id) return fail(res, 409, 'NOT_IN_SQUAD', 'Player is not in squad', {});
  if (b.type !== 'release' && (!to || !b.effective_date)) return validation(res, ['to_squad_id', 'effective_date']);
  const count = state.players.filter(p => p.squad_id === to?.squad_id).length; if (b.type !== 'release' && count >= state.max_squad_size) return fail(res, 409, 'SQUAD_FULL', 'Squad is full', {});
  const blocking = state.matches.find(m => m.home_squad_id === from.squad_id || m.away_squad_id === from.squad_id);
  const old = clone(player); if (b.type === 'release') player.squad_id = null; else { player.squad_id = to.squad_id; player.role = 'substitute'; }
  const registration = b.type === 'release' ? null : { player_id: player.player_id, league_id: b.league_id, squad_id: player.squad_id, parent_squad_id: b.type === 'loan' ? from.squad_id : null, registration_type: b.type, start_date: b.effective_date, loan_end_date: b.loan_end_date || null, role: player.role };
  const entry = { audit_id: `au-${state.audits.length + 1}`, action: b.type, player_id: player.player_id, league_id: b.league_id, from_squad_id: old.squad_id, to_squad_id: b.to_squad_id || null, effective_date: b.effective_date, state: blocking ? 'deferred_until_match_end' : 'active', who: b.requested_by, when: nowUtc(), why: b.reason || null };
  state.audits.push(entry); const result = { request_id: b.request_id, status: 'accepted', state: entry.state, blocking_match_id: blocking?.match_id || null, registration, audit_entry: entry }; state.requests.set(b.request_id, result); res.status(201).json(result);
});
app.get('/audit/v1/roster/history/:player', (req, res) => { for (const state of rosters.values()) if (state.players.some(p => p.player_id === req.params.player)) { const p = state.players.find(x => x.player_id === req.params.player); return res.json({ player_id: p.player_id, as_of: req.query.as_of || new Date().toISOString().slice(0, 10), league_id: state.league.league_id, current_squad_id: p.squad_id, parent_squad_id: null, history: state.audits.filter(a => a.player_id === p.player_id) }); } return fail(res, 404, 'PLAYER_NOT_FOUND', 'Player not found', {}); });

const receiptPdf = order => Buffer.from(`%PDF-1.4\nReceipt ${order}\n%%EOF`).toString('base64');
const prices = { 'var-jersey-001-M': 450000, 'var-jersey-001-L': 450000 };
app.post('/audit/v1/checkout', (req, res) => {
  const b = req.body || {}, bad = []; if (!ID.test(b.order_id || '')) bad.push('order_id'); if (typeof b.customer_id !== 'string' || !b.customer_id) bad.push('customer_id'); if (!Array.isArray(b.items) || !b.items.length) bad.push('items'); if (!b.payment || typeof b.payment.token !== 'string') bad.push('payment'); if (bad.length) return validation(res, bad);
  const old = orders.get(b.order_id); if (old) return canonical(old.request) === canonical(b) ? res.status(200).json(old.response) : fail(res, 409, 'DUPLICATE_ORDER_ID', 'order_id reused', {});
  for (const item of b.items) if (!(item.variant_id in store.stock)) return fail(res, 404, 'VARIANT_NOT_FOUND', 'Variant not found', { variant_id: item.variant_id });
  if (b.discount_code != null && b.discount_code !== 'WELCOME10') return fail(res, 400, 'INVALID_DISCOUNT_CODE', 'Bad discount code', {});
  for (const item of b.items) if (store.stock[item.variant_id] < item.quantity) return fail(res, 409, 'OUT_OF_STOCK', 'Insufficient stock', { variant_id: item.variant_id });
  for (const item of b.items) store.stock[item.variant_id] -= item.quantity;
  if (b.payment.token === 'tok_declined' || b.payment.token === 'tok_capture_fail') { for (const item of b.items) store.stock[item.variant_id] += item.quantity; return fail(res, 402, b.payment.token === 'tok_declined' ? 'PAYMENT_DECLINED' : 'PAYMENT_CAPTURE_FAILED', 'Payment failed', {}); }
  const items = b.items.map(i => ({ variant_id: i.variant_id, quantity: i.quantity, unit_price_minor: prices[i.variant_id] || 450000 })), subtotal_minor = items.reduce((sum, i) => sum + i.quantity * i.unit_price_minor, 0), discount_minor = b.discount_code === 'WELCOME10' ? Math.floor(subtotal_minor / 10) : 0, total_minor = subtotal_minor - discount_minor, payload = { order_id: b.order_id, customer_id: b.customer_id, items, subtotal_minor, discount_minor, total_minor, currency: 'PKR', paid_at: nowUtc() }, n = ++store.payment;
  const response = { order_id: b.order_id, status: 'paid', currency: 'PKR', items, subtotal_minor, discount_minor, total_minor, payment: { authorization_id: `auth_${n}`, capture_id: `cap_${n}`, state: 'captured' }, receipt: { payload, signature: sign(b.order_id, payload), pdf_base64: receiptPdf(b.order_id) } }; orders.set(b.order_id, { request: clone(b), response }); res.status(201).json(response);
});
app.get('/audit/v1/inventory/:id', (req, res) => req.params.id in store.stock ? res.json({ variant_id: req.params.id, stock: store.stock[req.params.id], reserved: store.reserved[req.params.id] || 0 }) : fail(res, 404, 'VARIANT_NOT_FOUND', 'Variant not found', {}));

function auth(req, res, next) {
  if (!req.path.startsWith('/api/v1/') || req.path === '/api/v1/auth/login') return next();
  const header = req.get('Authorization') || '', token = header.replace(/^Bearer\s+/, '');
  if (!token) return fail(res, 401, 'UNAUTHENTICATED', 'Authorization required', {});
  const data = verifyToken(token);
  if (!data) return fail(res, 401, 'UNAUTHENTICATED', 'Invalid token', {});
  req.user = data;
  return next();
}
app.use(auth);
function requireRbac(req, res, next) {
  const claims = verifyToken(req.get('Authorization'));
  if (!claims) return fail(res, 401, 'UNAUTHENTICATED', 'Invalid token', {});
  req.rbacUser = claims;
  return next();
}
function authorized(user, action, id) {
  if (user.role === 'super_admin') return true;
  const entity = action === 'league' ? resetState.leagues.get(id)
    : action === 'club' ? resetState.clubs.get(id)
      : action === 'player' ? resetState.players.get(id) : null;
  if (action === 'tenants' || action === 'platform') return false;
  if (!entity || (entity.tenant_id && entity.tenant_id !== user.tenant_id)) return false;
  if (action === 'league') return user.role === 'organizer' && entity.owner === user.sub;
  if (action === 'club') return user.role === 'manager' && entity.owner === user.sub;
  if (action === 'player') return (user.role === 'player' && entity.owner === user.sub)
    || (user.role === 'manager' && entity.club_id === user.club_id);
  return false;
}
app.post('/audit/v1/rbac-matrix', (_req, res) => res.json({
  tokens: {
    super_admin: tokenFor({ sub: 'admin@nascon.test', role: 'super_admin', tenant_id: null }),
    league_organizer: tokenFor({ sub: 'organizer@nascon.test', role: 'organizer', tenant_id: 'tenant-alpha', league_id: 'league-alpha-1' }),
    club_manager: tokenFor({ sub: 'manager@nascon.test', role: 'manager', tenant_id: 'tenant-alpha', club_id: 'club-alpha-1' }),
    player: tokenFor({ sub: 'player@nascon.test', role: 'player', tenant_id: 'tenant-alpha', player_id: 'player-alpha-1' }),
    viewer: tokenFor({ sub: 'viewer@nascon.test', role: 'viewer', tenant_id: 'tenant-alpha' })
  },
  context: { tenant_id: 'tenant-alpha', foreign_tenant_id: 'tenant-beta', own_league_id: 'league-alpha-1', other_league_id: 'league-alpha-2', foreign_league_id: 'league-beta-1', own_club_id: 'club-alpha-1', other_club_id: 'club-alpha-2', foreign_club_id: 'club-beta-1', own_player_id: 'player-alpha-1', other_player_id: 'player-alpha-2', foreign_player_id: 'player-beta-1' }
}));
function rbacProbe(action, id) {
  return (req, res) => {
    if (!authorized(req.rbacUser, action, id)) return fail(res, 403, 'FORBIDDEN', 'Access denied', {});
    res.json({ authorized: true });
  };
}
app.post('/audit/v1/rbac/tenants', requireRbac, rbacProbe('tenants'));
app.post('/audit/v1/rbac/leagues/:id/fixtures', requireRbac, (req, res) => rbacProbe('league', req.params.id)(req, res));
app.post('/audit/v1/rbac/clubs/:id/roster', requireRbac, (req, res) => rbacProbe('club', req.params.id)(req, res));
app.post('/audit/v1/rbac/clubs/:id/products', requireRbac, (req, res) => rbacProbe('club', req.params.id)(req, res));
app.patch('/audit/v1/rbac/players/:id', requireRbac, (req, res) => rbacProbe('player', req.params.id)(req, res));
app.get('/audit/v1/rbac/clubs/:id', requireRbac, (req, res) => {
  const club = resetState.clubs.get(req.params.id);
  if (!club || (club.tenant_id !== 'tenant-alpha' && req.rbacUser.role !== 'super_admin')) return fail(res, 403, 'FORBIDDEN', 'Access denied', {});
  res.json({ authorized: true });
});
app.get('/audit/v1/rbac/platform/config', requireRbac, rbacProbe('platform'));
app.post('/api/v1/auth/login', (req, res) => { const user = resetState.users.get(req.body?.email); if (!user || req.body.password !== 'Nascon@26') return fail(res, 401, 'UNAUTHENTICATED', 'Invalid credentials', {}); return res.json({ access_token: tokenFor({ sub: req.body.email, ...user }), token_type: 'Bearer', user: { email: req.body.email, ...user } }); });
const apiHits = new Map();
app.use('/api/v1', (req, res, next) => {
  const current = Date.now();
  const key = req.ip;
  const recent = (apiHits.get(key) || []).filter(timestamp => current - timestamp < 10000);
  if (recent.length >= 100) {
    res.set('Retry-After', '10');
    return fail(res, 429, 'RATE_LIMITED', 'Too many requests', {});
  }
  recent.push(current);
  apiHits.set(key, recent);
  return next();
});
app.get('/api/v1/ping', (_, res) => res.json({ pong: true }));
app.post('/audit/v1/offline-sync', (req, res) => { const { device_id, actions } = req.body || {}; if (typeof device_id !== 'string' || !Array.isArray(actions) || actions.length < 1 || actions.length > 100) return validation(res, ['device_id', 'actions']); const results = actions.map((action, index) => { const key = `${device_id}:${action.action_id}`; if (processedActions.has(key)) return { action_id: action.action_id, status: 'duplicate', resolution: 'skipped_duplicate', error_code: null, processed_order: index + 1, server_version: action.base_version, signature: null }; processedActions.set(key, true); if (action.type === 'score_event') { const fake = { body: action.payload }; const match = matches.get(action.payload.match_id); if (!match) return { action_id: action.action_id, status: 'rejected', resolution: 'server_wins', error_code: 'MATCH_NOT_FOUND', processed_order: index + 1, server_version: 0, signature: null }; const event = { ...action.payload, payload: action.payload.payload }; const signature = sign(event.event_id, event.payload); match.events.push({ ...event, signature }); return { action_id: action.action_id, status: 'applied', resolution: action.base_version < match.events.length - 1 ? 'rebased_append' : 'applied', error_code: null, processed_order: index + 1, server_version: match.events.length, signature }; } return { action_id: action.action_id, status: 'rejected', resolution: 'server_wins', error_code: 'VALIDATION_ERROR', processed_order: index + 1, server_version: action.base_version, signature: null }; }); res.json({ device_id, results, summary: { applied: results.filter(x => x.status === 'applied').length, rejected: results.filter(x => x.status === 'rejected').length, duplicate: results.filter(x => x.status === 'duplicate').length } }); });

app.use((error, _req, res, _next) => error.type === 'entity.too.large' ? fail(res, 413, 'PAYLOAD_TOO_LARGE', 'Body too large', {}) : error.type === 'entity.parse.failed' ? fail(res, 400, 'VALIDATION_ERROR', 'Malformed JSON', { fields: [] }) : fail(res, 500, 'INTERNAL_ERROR', 'Server error', {}));
app.listen(8080, '0.0.0.0', () => console.log('up'));
