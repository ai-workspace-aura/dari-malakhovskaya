'use strict';

const CH = {
  tg_open:   {name: 'Открытый ТГ', short: 'ТГ'},
  tg_closed: {name: 'Закрытый ТГ', short: 'Закр. ТГ'},
  stories:   {name: 'Сторис', short: 'Сторис'},
  reels:     {name: 'Рилс', short: 'Рилс'},
  email:     {name: 'Email', short: 'Email'},
};
const CH_KEYS = Object.keys(CH);
const STATUS = {planned: 'Запланировано', in_work: 'В работе', ready: 'Готово', published: 'Опубликовано'};
const REACH_LABEL = {reels: 'Просмотры', email: 'Открытия'};
const MONTHS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const MONTHS_GEN = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
const DOW = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => Math.round(n || 0).toLocaleString('ru-RU');
const rub = n => fmt(n) + ' ₽';
const pct = (a, b) => b > 0 ? (a / b * 100).toLocaleString('ru-RU', {maximumFractionDigits: 2}) + '%' : '—';
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const todayIso = () => iso(new Date());
const humanDate = s => { const [y, m, d] = s.split('-').map(Number); return `${d} ${MONTHS_GEN[m - 1]}`; };
const shortDate = s => { const [, m, d] = s.split('-'); return `${d}.${m}`; };
const chColor = ch => `var(--c-${ch})`;

const state = {
  user: null, settings: {}, plan: {days: [], items: []},
  month: null, chFilter: new Set(CH_KEYS), planView: 'cal',
  stChannel: 'tg_open', metrics: [], payments: [], summary: null,
};

// ---------- запросы ----------

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || 'GET',
    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'admin'},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: 'same-origin',
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* пустой ответ */ }
  if (res.status === 401 && !['/api/login', '/api/setup'].includes(path)) { await showLogin(); throw new Error(data.error || 'Нужно войти'); }
  if (!res.ok) throw new Error(data.error || `Ошибка ${res.status}`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
}
const fail = e => toast(e.message || String(e));

// ---------- вход ----------

let setupMode = false;

async function showLogin() {
  $('appView').hidden = true;
  $('loginView').hidden = false;
  try { setupMode = (await fetch('/api/setup').then(r => r.json())).needs_setup === true; } catch (e) { setupMode = false; }
  $('loginTitle').textContent = setupMode ? 'Первая учётка' : 'Вход';
  $('loginHint').textContent = setupMode ? 'В админке ещё нет пользователей. Придумайте почту и пароль (от 8 символов): они станут вашим входом.' : '';
  $('loginBtn').textContent = setupMode ? 'Создать и войти' : 'Войти';
}

$('loginForm').onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  $('loginErr').textContent = '';
  try {
    await api(setupMode ? '/api/setup' : '/api/login', {method: 'POST', body: {email: f.get('email'), password: f.get('password')}});
    boot();
  } catch (err) { $('loginErr').textContent = err.message; }
};

$('logout').onclick = async () => { await api('/api/logout', {method: 'POST'}).catch(() => {}); showLogin(); };

async function boot() {
  let me;
  try { me = await api('/api/me'); } catch (e) {
    if (!$('loginView').hidden) return;  // 401: уже показали вход
    $('loginView').hidden = false;
    $('loginErr').textContent = 'Сервер не отвечает: ' + e.message;
    return;
  }
  state.user = me.user;
  state.settings = me.settings;
  $('whoName').textContent = me.user.name || me.user.email;
  $('loginView').hidden = true;
  $('appView').hidden = false;
  if (!state.month) {
    const t = new Date();
    const first = state.settings.period_from ? new Date(state.settings.period_from + 'T00:00') : t;
    // во время запуска открываем текущий месяц, до него — месяц старта
    state.month = t < first ? new Date(first.getFullYear(), first.getMonth(), 1) : new Date(t.getFullYear(), t.getMonth(), 1);
  }
  initStatsPeriod();
  fillSelects();
  openTab(localGet('tab') || 'plan');
}

function localGet(k) { try { return localStorage.getItem('admin.' + k); } catch (e) { return null; } }
function localSet(k, v) { try { localStorage.setItem('admin.' + k, v); } catch (e) { /* приватный режим */ } }

// ---------- вкладки ----------

document.querySelectorAll('.tab').forEach(t => t.onclick = () => openTab(t.dataset.tab));

function openTab(name) {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x.dataset.tab === name));
  document.querySelectorAll('.panel').forEach(x => x.classList.toggle('active', x.id === 'panel-' + name));
  localSet('tab', name);
  ({plan: loadPlan, stats: loadStats, fin: loadFinance, settings: loadSettings})[name]().catch(fail);
}

// ---------- контент-план ----------

async function loadPlanData() {
  state.plan = await api('/api/plan');
}

async function loadPlan() {
  await loadPlanData();
  renderPlan();
}

function renderChFilter() {
  $('chFilter').innerHTML = CH_KEYS.map(ch =>
    `<span class="chip ${state.chFilter.has(ch) ? '' : 'off'}" data-ch="${ch}"><i class="sw" style="background:${chColor(ch)}"></i>${CH[ch].name}</span>`).join('');
  $('chFilter').querySelectorAll('.chip').forEach(c => c.onclick = () => {
    const ch = c.dataset.ch;
    state.chFilter.has(ch) ? state.chFilter.delete(ch) : state.chFilter.add(ch);
    renderPlan();
  });
}

function renderPlan() {
  renderChFilter();
  $('planView').value = state.planView;
  const m = state.month;
  $('calMonth').textContent = `${MONTHS[m.getMonth()]} ${m.getFullYear()}`;
  if (state.planView === 'list') return renderPlanList();
  const daysBy = Object.fromEntries(state.plan.days.map(d => [d.date, d]));
  const itemsBy = {};
  state.plan.items.forEach(it => { if (state.chFilter.has(it.channel)) (itemsBy[it.date] ||= []).push(it); });
  const start = new Date(m);
  start.setDate(1 - ((m.getDay() + 6) % 7));
  const today = todayIso();
  let html = DOW.map(d => `<div class="dow">${d}</div>`).join('');
  for (let i = 0; i < 42; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    if (i >= 35 && d.getMonth() !== m.getMonth()) break;
    const key = iso(d);
    const pd = daysBy[key];
    const items = (itemsBy[key] || []).sort((a, b) => CH_KEYS.indexOf(a.channel) - CH_KEYS.indexOf(b.channel));
    html += `<div class="day ${d.getMonth() !== m.getMonth() ? 'other' : ''} ${key === today ? 'today' : ''} ${pd || items.length ? '' : 'blank'}" data-date="${key}">
      <span class="dn">${d.getDate()}<span class="mut small" style="font-weight:400"> ${window.innerWidth < 700 ? DOW[(d.getDay() + 6) % 7] : ''}</span></span>
      ${pd && pd.title ? `<div class="dt">${esc(pd.title)}</div>` : ''}
      ${items.map(it => `<div class="pill" style="border-color:${chColor(it.channel)}" title="${esc(CH[it.channel].name + ' · ' + STATUS[it.status])}"><i class="st ${it.status}"></i>${CH[it.channel].short}</div>`).join('')}
    </div>`;
  }
  $('planBody').innerHTML = `<div class="cal">${html}</div>`;
  $('planBody').querySelectorAll('.day').forEach(el => el.onclick = () => openDay(el.dataset.date));
}

function renderPlanList() {
  const m = state.month;
  const prefix = `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}`;
  const items = state.plan.items.filter(it => it.date.startsWith(prefix) && state.chFilter.has(it.channel));
  if (!items.length) { $('planBody').innerHTML = '<div class="tablewrap"><div class="empty">В этом месяце публикаций нет</div></div>'; return; }
  $('planBody').innerHTML = `<div class="tablewrap"><table class="t"><thead><tr><th>Дата</th><th>Канал</th><th>Тема</th><th>Формат</th><th>Статус</th></tr></thead><tbody>
    ${items.map(it => `<tr>
      <td style="white-space:nowrap"><a href="#" data-date="${it.date}">${shortDate(it.date)}</a></td>
      <td style="white-space:nowrap"><span class="pill" style="border-color:${chColor(it.channel)};display:inline-flex">${CH[it.channel].name}</span></td>
      <td>${esc(it.title)}</td>
      <td class="mut small" style="max-width:360px">${esc((it.format || '').slice(0, 140))}</td>
      <td><select class="cellin" data-id="${it.id}">${statusOptions(it.status)}</select></td></tr>`).join('')}
  </tbody></table></div>`;
  $('planBody').querySelectorAll('a[data-date]').forEach(a => a.onclick = e => { e.preventDefault(); openDay(a.dataset.date); });
  $('planBody').querySelectorAll('select[data-id]').forEach(s => s.onchange = () => saveItem(+s.dataset.id, {status: s.value}));
}

const statusOptions = cur => Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${k === cur ? 'selected' : ''}>${v}</option>`).join('');

$('planView').onchange = e => { state.planView = e.target.value; renderPlan(); };
$('calPrev').onclick = () => { state.month = new Date(state.month.getFullYear(), state.month.getMonth() - 1, 1); renderPlan(); };
$('calNext').onclick = () => { state.month = new Date(state.month.getFullYear(), state.month.getMonth() + 1, 1); renderPlan(); };
$('calToday').onclick = () => { const t = new Date(); state.month = new Date(t.getFullYear(), t.getMonth(), 1); renderPlan(); };

async function saveItem(id, patch) {
  try {
    const upd = await api(`/api/items/${id}`, {method: 'PUT', body: patch});
    const i = state.plan.items.findIndex(x => x.id === id);
    if (i >= 0) state.plan.items[i] = upd;
    return upd;
  } catch (e) { fail(e); }
}

// ---------- панель дня ----------

let openDate = null;

function closeDay() {
  $('drawer').classList.remove('open');
  $('overlay').classList.remove('open');
  openDate = null;
  renderPlan();
}
$('overlay').onclick = closeDay;
document.addEventListener('keydown', e => { if (e.key === 'Escape' && openDate) closeDay(); });

const DAY_FIELDS = [
  ['belief', 'Что должен понять читатель'], ['audience', 'Кому говорим'], ['scene', 'Узнаваемая сцена'],
  ['bridge', 'Как день продаёт идею «Союза»'], ['case_note', 'Видеоистория'], ['needed', 'Что спросить у Дари / проверить'],
];

function openDay(date) {
  openDate = date;
  const pd = state.plan.days.find(d => d.date === date) || {date};
  const stages = state.settings.stages || [];
  const stage = pd.stage != null ? stages[pd.stage] : null;
  const items = state.plan.items.filter(it => it.date === date)
    .sort((a, b) => CH_KEYS.indexOf(a.channel) - CH_KEYS.indexOf(b.channel));
  const dr = $('drawer');
  dr.innerHTML = `
    <div class="head">
      <div>
        <div class="mut small">${humanDate(date)}${stage ? ' · ' + esc(stage.title) : ''}</div>
        <h2><input class="cellin" id="dayTitle" style="font-size:20px;font-weight:600;padding:2px 4px;margin-left:-4px" value="${esc(pd.title || '')}" placeholder="Тема дня"></h2>
      </div>
      <button class="btn ghost" id="dayClose" aria-label="Закрыть">✕</button>
    </div>
    <details ${pd.belief ? '' : 'open'}><summary>Смысл дня</summary>
      ${DAY_FIELDS.map(([k, l]) => `<label class="lbl">${l}</label><textarea class="field" data-day="${k}" rows="2">${esc(pd[k] || '')}</textarea>`).join('')}
    </details>
    <div id="dayItems">${items.map(itemCard).join('') || '<p class="mut">На этот день публикаций нет.</p>'}</div>
    <div class="form-row" style="margin-top:16px">
      <select class="field" id="newCh">${CH_KEYS.map(ch => `<option value="${ch}">${CH[ch].name}</option>`).join('')}</select>
      <button class="btn" id="newItem">+ Добавить публикацию</button>
    </div>`;
  $('drawer').classList.add('open');
  $('overlay').classList.add('open');
  $('dayClose').onclick = closeDay;
  $('dayTitle').onchange = e => saveDay(date, {title: e.target.value});
  dr.querySelectorAll('[data-day]').forEach(t => t.onchange = () => saveDay(date, {[t.dataset.day]: t.value}));
  bindItemCards(dr);
  $('newItem').onclick = async () => {
    try {
      const it = await api('/api/items', {method: 'POST', body: {date, channel: $('newCh').value, title: pd.title || '', status: 'planned'}});
      state.plan.items.push(it);
      openDay(date);
    } catch (e) { fail(e); }
  };
}

async function saveDay(date, patch) {
  try {
    const d = await api(`/api/plan/days/${date}`, {method: 'PUT', body: patch});
    const i = state.plan.days.findIndex(x => x.date === date);
    i >= 0 ? state.plan.days[i] = d : state.plan.days.push(d);
    toast('Сохранено');
  } catch (e) { fail(e); }
}

function itemCard(it) {
  const f = (k, label, rows) => `<label class="lbl">${label}</label>` + (rows
    ? `<textarea class="field" data-f="${k}" rows="${rows}">${esc(it[k] || '')}</textarea>`
    : `<input class="field" style="width:100%" data-f="${k}" value="${esc(it[k] || '')}">`);
  return `<div class="item" data-id="${it.id}" style="border-left-color:${chColor(it.channel)}">
    <div class="ih">
      <span class="name">${CH[it.channel].name}</span>
      <span class="saved">Сохранено</span>
      <select class="field" data-f="status">${statusOptions(it.status)}</select>
      <button class="btn ghost danger" data-del title="Удалить публикацию">Удалить</button>
    </div>
    ${f('title', 'Заголовок')}
    ${f('format', 'Формат', 2)}
    <details style="margin:10px 0 0;padding:8px 12px"><summary class="small">Сценарий и призыв</summary>
      ${f('script', 'О чём писать, что показать', 6)}
      ${f('cta', 'Что предлагаем читательнице', 2)}
    </details>
    ${f('link', 'Ссылка на публикацию')}
    ${f('notes', 'Заметки команды', 2)}
  </div>`;
}

function bindItemCards(root) {
  root.querySelectorAll('.item').forEach(card => {
    const id = +card.dataset.id;
    card.querySelectorAll('[data-f]').forEach(inp => inp.onchange = async () => {
      if (await saveItem(id, {[inp.dataset.f]: inp.value})) {
        const s = card.querySelector('.saved');
        s.classList.add('show');
        setTimeout(() => s.classList.remove('show'), 1400);
      }
    });
    card.querySelector('[data-del]').onclick = async () => {
      if (!confirm('Удалить эту публикацию из плана?')) return;
      try {
        await api(`/api/items/${id}`, {method: 'DELETE'});
        state.plan.items = state.plan.items.filter(x => x.id !== id);
        openDay(openDate);
      } catch (e) { fail(e); }
    };
  });
}

// ---------- статистика ----------

function initStatsPeriod() {
  if (!$('stFrom').value) {
    $('stFrom').value = state.settings.period_from || '';
    $('stTo').value = state.settings.period_to || '';
  }
}

document.querySelectorAll('[data-preset]').forEach(b => b.onclick = () => {
  const p = b.dataset.preset, t = new Date();
  if (p === 'launch') { $('stFrom').value = state.settings.period_from; $('stTo').value = state.settings.period_to; }
  if (p === 'today') { $('stFrom').value = $('stTo').value = iso(t); }
  if (p === '7') { const f = new Date(t); f.setDate(t.getDate() - 6); $('stFrom').value = iso(f); $('stTo').value = iso(t); }
  loadStats().catch(fail);
});
$('stFrom').onchange = $('stTo').onchange = () => loadStats().catch(fail);

async function loadStats() {
  const q = new URLSearchParams({from: $('stFrom').value, to: $('stTo').value});
  const [r] = await Promise.all([api('/api/metrics?' + q), state.plan.days.length ? null : loadPlanData()]);
  state.metrics = r.rows;
  renderFunnels();
  renderStChannel();
  renderStTable();
  loadLinks().catch(fail);
}

function renderFunnels() {
  const tot = Object.fromEntries(CH_KEYS.map(ch => [ch, {posts: 0, reach: 0, clicks: 0}]));
  state.metrics.forEach(r => { const t = tot[r.channel]; t.posts += r.posts || 0; t.reach += r.reach || 0; t.clicks += r.clicks || 0; });
  const countLabel = {tg_open: 'Постов', tg_closed: 'Постов', stories: 'Сторис', reels: 'Рилс', email: 'Рассылок'};
  $('funnels').innerHTML = CH_KEYS.map(ch => {
    const t = tot[ch];
    return `<div class="funnel" style="border-top-color:${chColor(ch)}">
      <h3>${CH[ch].name}</h3>
      <div class="step"><span class="mut">${countLabel[ch]}</span><b>${fmt(t.posts)}</b></div>
      <div class="step"><span class="mut">${REACH_LABEL[ch] || 'Охват'}</span><b>${fmt(t.reach)}</b></div>
      <div class="conv">${t.posts ? '≈ ' + fmt(t.reach / t.posts) + ' на единицу' : '&nbsp;'}</div>
      <div class="step"><span class="mut">Переходы</span><b>${fmt(t.clicks)}</b></div>
      <div class="conv">CTR ${pct(t.clicks, t.reach)}</div>
    </div>`;
  }).join('');
}

function renderStChannel() {
  $('stChannel').innerHTML = CH_KEYS.map(ch =>
    `<span class="chip ${ch === state.stChannel ? '' : 'off'}" data-ch="${ch}"><i class="sw" style="background:${chColor(ch)}"></i>${CH[ch].name}</span>`).join('');
  $('stChannel').querySelectorAll('.chip').forEach(c => c.onclick = () => { state.stChannel = c.dataset.ch; renderStChannel(); renderStTable(); });
}

function renderStTable() {
  const ch = state.stChannel;
  const rows = state.metrics.filter(r => r.channel === ch);
  const cell = (r, f) => {
    const man = r.manual[f];
    return `<input class="cellin num ${man != null ? 'manual' : ''}" inputmode="numeric" data-date="${r.date}" data-f="${f}"
      value="${man != null ? man : ''}" placeholder="${fmt(r.auto[f])}">`;
  };
  $('stTable').innerHTML = `<table class="t"><thead><tr><th>Дата</th><th>Тема дня</th><th class="num">Публикаций</th><th class="num">${REACH_LABEL[ch] || 'Охват'}</th><th class="num">Переходы</th><th class="num">CTR</th></tr></thead><tbody>
    ${rows.map(r => {
      const pd = state.plan.days.find(d => d.date === r.date);
      return `<tr><td style="white-space:nowrap">${shortDate(r.date)}</td><td class="mut small">${esc(pd ? pd.title : '')}</td>
      <td style="width:120px">${cell(r, 'posts')}</td><td style="width:140px">${cell(r, 'reach')}</td><td style="width:120px">${cell(r, 'clicks')}</td>
      <td class="num mut small">${pct(r.clicks, r.reach)}</td></tr>`;
    }).join('')}
  </tbody></table>`;
  $('stTable').querySelectorAll('input').forEach(inp => inp.onchange = async () => {
    const v = inp.value.replace(/\s/g, '');
    if (v !== '' && !/^\d+$/.test(v)) { toast('Нужно целое число'); return; }
    try {
      await api('/api/metrics', {method: 'PUT', body: {date: inp.dataset.date, channel: ch, field: inp.dataset.f, value: v}});
      await loadStats();
    } catch (e) { fail(e); }
  });
}

async function loadLinks() {
  const r = await api('/api/links');
  const base = r.base_url || location.origin;
  if (!r.links.length) { $('linksTable').innerHTML = '<div class="empty">Ссылок пока нет</div>'; return; }
  $('linksTable').innerHTML = `<table class="t"><thead><tr><th>Короткая ссылка</th><th>Куда ведёт</th><th>Канал</th><th>День</th><th class="num">Переходы</th><th></th></tr></thead><tbody>
    ${r.links.map(l => `<tr>
      <td><code>${esc(base)}/go/${esc(l.slug)}</code> <button class="btn ghost small" data-copy="${esc(base)}/go/${esc(l.slug)}">Копировать</button></td>
      <td class="small" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(l.target)}">${esc(l.target)}${l.note ? `<div class="mut">${esc(l.note)}</div>` : ''}</td>
      <td>${CH[l.channel] ? CH[l.channel].name : esc(l.channel)}</td>
      <td style="white-space:nowrap">${l.date ? shortDate(l.date) : '—'}</td>
      <td class="num">${fmt(l.clicks)}</td>
      <td><button class="btn ghost danger" data-del="${l.id}">Удалить</button></td></tr>`).join('')}
  </tbody></table>`;
  $('linksTable').querySelectorAll('[data-copy]').forEach(b => b.onclick = () =>
    navigator.clipboard.writeText(b.dataset.copy).then(() => toast('Ссылка скопирована'), () => toast(b.dataset.copy)));
  $('linksTable').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('Удалить ссылку вместе с её переходами? Опубликованная ссылка перестанет работать.')) return;
    try { await api(`/api/links/${b.dataset.del}`, {method: 'DELETE'}); loadStats(); } catch (e) { fail(e); }
  });
}

$('linkForm').onsubmit = async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  try {
    await api('/api/links', {method: 'POST', body});
    e.target.reset();
    toast('Ссылка создана');
    loadStats();
  } catch (err) { fail(err); }
};

// ---------- финансы ----------

function fillSelects() {
  const s = state.settings;
  $('linkChannel').innerHTML = CH_KEYS.map(ch => `<option value="${ch}">${CH[ch].name}</option>`).join('');
  const opt = (sel, first, list) => { const v = $(sel).value; $(sel).innerHTML = `<option value="">${first}</option>` + list.map(x => `<option>${esc(x)}</option>`).join(''); $(sel).value = v; };
  opt('payStatus', 'Все статусы', s.statuses || []);
  opt('payManager', 'Все менеджеры', s.managers || []);
  opt('payTariff', 'Все тарифы', s.tariffs || []);
}

async function loadFinance() {
  const r = await api('/api/finance');
  state.payments = r.payments;
  state.summary = r.summary;
  renderFinance();
}

function renderFinance() {
  const s = state.summary;
  if (document.activeElement !== $('finPlan')) $('finPlan').value = fmt(s.plan);
  $('finRev').textContent = rub(s.revenue);
  $('finPct').textContent = pct(s.revenue, s.plan);
  $('finCnt').textContent = fmt(s.count);
  $('finAvg').textContent = rub(s.avg);
  $('finBar').style.width = Math.min(100, s.plan ? s.revenue / s.plan * 100 : 0) + '%';
  renderPayments();
  const by = (title, list) => `<div class="card"><h3>${title}</h3>${list.length ? `<table class="t"><tbody>${list.map(x =>
    `<tr><td>${esc(x.name)}</td><td class="num mut">${fmt(x.count)}</td><td class="num">${rub(x.sum)}</td></tr>`).join('')}</tbody></table>` : '<p class="mut small">Оплат пока нет</p>'}</div>`;
  $('finBy').innerHTML = by('По тарифам', s.by.tariff) + by('По менеджерам', s.by.manager) + by('По способам оплаты', s.by.method);
}

function renderPayments() {
  const s = state.settings;
  const q = $('payQ').value.trim().toLowerCase();
  const fs = $('payStatus').value, fm = $('payManager').value, ft = $('payTariff').value;
  const list = state.payments.filter(p =>
    (!q || [p.client, p.email, p.gc_id].some(v => (v || '').toLowerCase().includes(q))) &&
    (!fs || p.status === fs) && (!fm || p.manager === fm) && (!ft || p.tariff === ft));
  const sel = (p, k, opts) => {
    const all = [...opts]; if (p[k] && !all.includes(p[k])) all.push(p[k]);
    return `<select class="cellin" data-id="${p.id}" data-f="${k}"><option value="">—</option>${all.map(o => `<option ${o === p[k] ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
  };
  const inp = (p, k, cls = '', type = 'text') => `<input class="cellin ${cls}" type="${type}" data-id="${p.id}" data-f="${k}" value="${esc(cls === 'num' && p[k] != null ? fmt(p[k]) : (p[k] ?? ''))}">`;
  if (!state.payments.length) {
    $('payTable').innerHTML = '<div class="empty">Оплат пока нет. Добавьте вручную, загрузите CSV-выгрузку заказов из GetCourse или подключите интеграцию в настройках.</div>';
    return;
  }
  $('payTable').innerHTML = `<table class="t"><thead><tr>
    <th>Дата</th><th>Клиент</th><th>Тариф</th><th class="num">Стоимость</th><th class="num">Оплачено</th>
    <th>Способ оплаты</th><th>Кто закрыл</th><th>Статус</th><th>№ GetCourse</th><th></th></tr></thead><tbody>
    ${list.map(p => `<tr>
      <td style="min-width:130px">${inp(p, 'date', '', 'date')}</td>
      <td style="min-width:170px">${inp(p, 'client')}${p.email ? `<div class="mut small" style="padding-left:7px">${esc(p.email)}</div>` : ''}</td>
      <td>${sel(p, 'tariff', s.tariffs || [])}</td>
      <td style="width:120px">${inp(p, 'amount', 'num')}</td>
      <td style="width:120px">${inp(p, 'paid', 'num')}</td>
      <td>${sel(p, 'method', s.methods || [])}</td>
      <td>${sel(p, 'manager', s.managers || [])}</td>
      <td>${sel(p, 'status', s.statuses || [])}</td>
      <td style="width:110px">${inp(p, 'gc_id')}</td>
      <td><button class="btn ghost danger" data-del="${p.id}" title="Удалить">✕</button></td></tr>`).join('')}
  </tbody></table>${list.length ? '' : '<div class="empty">Ничего не найдено</div>'}`;
  $('payTable').querySelectorAll('[data-f]').forEach(el => el.onchange = async () => {
    let v = el.value;
    if (el.classList.contains('num')) v = v.replace(/\s/g, '').replace(',', '.');
    try {
      await api(`/api/payments/${el.dataset.id}`, {method: 'PUT', body: {[el.dataset.f]: v}});
      await loadFinance();
    } catch (e) { fail(e); }
  });
  $('payTable').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('Удалить оплату из таблицы?')) return;
    try { await api(`/api/payments/${b.dataset.del}`, {method: 'DELETE'}); loadFinance(); } catch (e) { fail(e); }
  });
}

['payQ', 'payStatus', 'payManager', 'payTariff'].forEach(id => $(id).oninput = renderPayments);

$('payAdd').onclick = async () => {
  try {
    await api('/api/payments', {method: 'POST', body: {date: todayIso(), status: 'Оплачен', tariff: (state.settings.tariffs || [])[0] || ''}});
    await loadFinance();
    const first = $('payTable').querySelector('[data-f="client"]');
    if (first) first.focus();
  } catch (e) { fail(e); }
};

$('finPlan').onchange = async () => {
  const v = +$('finPlan').value.replace(/\s/g, '').replace(',', '.') || 0;
  try {
    state.settings = await api('/api/settings', {method: 'PUT', body: {revenue_plan: v}});
    loadFinance();
  } catch (e) { fail(e); }
};

$('payImport').onclick = () => $('payFile').click();
$('payFile').onchange = async e => {
  const file = e.target.files[0];
  if (!file) return;
  const buf = await file.arrayBuffer();
  let text;
  // GetCourse отдаёт CSV то в UTF-8, то в Windows-1251
  try { text = new TextDecoder('utf-8', {fatal: true}).decode(buf); } catch (err) { text = new TextDecoder('windows-1251').decode(buf); }
  try {
    const r = await api('/api/payments/import', {method: 'POST', body: {text}});
    toast(`Импорт: новых ${r.created}, обновлено ${r.updated}${r.skipped ? ', пропущено ' + r.skipped : ''}`);
    loadFinance();
  } catch (err) { fail(err); }
  e.target.value = '';
};

// ---------- настройки ----------

async function loadSettings() {
  const s = state.settings;
  $('setManagers').value = (s.managers || []).join('\n');
  $('setTariffs').value = (s.tariffs || []).join('\n');
  $('setMethods').value = (s.methods || []).join('\n');
  $('setFrom').value = s.period_from || '';
  $('setTo').value = s.period_to || '';
  const r = await api('/api/integrations');
  const names = {getcourse: 'GetCourse — заказы и оплаты', instagram: 'Instagram — сторис и рилс', telegram: 'Telegram — просмотры постов'};
  $('intTable').innerHTML = `<table class="t"><thead><tr><th>Источник</th><th>Статус</th><th>Последняя синхронизация</th><th></th></tr></thead><tbody>
    ${Object.entries(r.sources).map(([k, v]) => `<tr><td>${names[k]}</td>
      <td>${v.enabled ? '<span class="badge ok">Включено</span>' : '<span class="badge">Не настроено</span>'}</td>
      <td class="small">${v.last ? `<span class="badge ${v.last.ok ? 'ok' : 'bad'}">${v.last.ok ? 'OK' : 'Ошибка'}</span> ${esc(v.last.ts.replace('T', ' ').slice(0, 16))}<div class="mut">${esc(v.last.message)}</div>` : '<span class="mut">ещё не было</span>'}</td>
      <td>${v.enabled ? `<button class="btn" data-sync="${k}">Обновить</button>` : ''}</td></tr>`).join('')}
  </tbody></table>`;
  $('intTable').querySelectorAll('[data-sync]').forEach(b => b.onclick = async () => {
    try { const x = await api(`/api/sync/${b.dataset.sync}`, {method: 'POST'}); toast(x.message); } catch (e) { fail(e); }
  });
  const base = r.base_url || location.origin;
  $('intHint').innerHTML = `Ключи и токены хранятся в файле <code>config.json</code> на сервере, в интерфейс они не попадают. Как их получить, описано в README.<br>
    Вебхук GetCourse (процесс по заказам → «Вызвать URL»), пример — точные переменные подставьте из редактора процесса: <code>${esc(base)}/hooks/getcourse?token=…&amp;id={object.id}&amp;status={object.status}&amp;cost={object.cost_money_value}&amp;payed={object.payed_money_value}&amp;client={object.user.first_name}&amp;email={object.user.email}&amp;tariff={object.positions}&amp;manager={object.manager.name}</code>
    ${r.webhook ? '' : '<br><span class="badge warn">токен вебхука не задан</span>'}`;
}

$('setSave').onclick = async () => {
  const lines = id => $(id).value.split('\n').map(x => x.trim()).filter(Boolean);
  try {
    state.settings = await api('/api/settings', {method: 'PUT', body: {
      managers: lines('setManagers'), tariffs: lines('setTariffs'), methods: lines('setMethods'),
      period_from: $('setFrom').value, period_to: $('setTo').value,
    }});
    fillSelects();
    toast('Настройки сохранены');
  } catch (e) { fail(e); }
};

window.addEventListener('resize', () => { if ($('panel-plan').classList.contains('active') && state.planView === 'cal') renderPlan(); });

boot();
