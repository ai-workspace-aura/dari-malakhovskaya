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
  renderIntegrations(await api('/api/integrations'));
}

// ---------- интеграции ----------

const INT_TITLES = {getcourse: 'GetCourse — заказы и оплаты', instagram: 'Instagram — сторис и рилс', telegram: 'Telegram — просмотры постов'};

function intStatus(src) {
  const l = src.last;
  if (!l) return '<div class="status mut">Синхронизаций ещё не было</div>';
  return `<div class="status"><span class="badge ${l.ok ? 'ok' : 'bad'}">${l.ok ? 'OK' : 'Ошибка'}</span>
    <span class="mut">${esc(l.ts.replace('T', ' ').slice(0, 16))}</span><div class="mut">${esc(l.message)}</div></div>`;
}

function intField(name, f, label, opts = {}) {
  const secret = !('value' in f);
  const ph = secret ? (f.set ? 'Сохранён. Вставьте новый, чтобы заменить' : 'Вставьте значение') : (opts.placeholder || '');
  return `<label class="lbl">${label}${secret && f.set ? ' <span class="badge ok">задан</span>' : ''}</label>
    <input class="field" data-k="${name}" type="${secret ? 'password' : (opts.type || 'text')}" autocomplete="off"
      value="${secret ? '' : esc(f.value)}" placeholder="${esc(ph)}">${opts.hint ? `<div class="mut small" style="margin-top:4px">${opts.hint}</div>` : ''}`;
}

function intHead(key, src) {
  return `<div class="top2"><h3 style="margin:0">${INT_TITLES[key]}</h3>
    <label class="switch"><input type="checkbox" data-enable="${key}" ${src.enabled ? 'checked' : ''}>Включено</label></div>
    ${intStatus(src)}`;
}

function renderIntegrations(r) {
  const S = r.sources, base = r.base_url || location.origin;
  const gc = S.getcourse, ig = S.instagram, tg = S.telegram;
  const hook = gc.webhook_token
    ? `<code>${esc(base)}/hooks/getcourse?token=${esc(gc.webhook_token)}&amp;id={object.id}&amp;status={object.status}&amp;cost={object.cost_money_value}&amp;payed={object.payed_money_value}&amp;email={object.user.email}&amp;client={object.user.first_name}&amp;tariff={object.positions}&amp;manager={object.manager.name}</code>
       <div class="mut small" style="margin-top:4px">Точные названия переменных возьмите в редакторе процесса GetCourse.</div>`
    : '<span class="mut small">Токен ещё не создан</span>';
  const chSel = (name, label) => `<label class="lbl">${label}</label>
    <select class="field" data-k="${name}"><option value="${esc(tg.fields[name].value)}">${esc(tg.fields[name].value || '— не выбран —')}</option></select>`;
  let tgAccount;
  if (tg.logged_in) {
    tgAccount = `<div class="row2"><span>Подключён аккаунт <b>${esc(tg.account || '')}</b></span>
      <button class="btn ghost danger" id="tgLogout">Отключить</button></div>`;
  } else if (tg.pending === 'code' || tg.pending === 'password') {
    const isPw = tg.pending === 'password';
    tgAccount = `<div class="mut small" style="margin-top:6px">${isPw ? 'На аккаунте стоит облачный пароль Telegram — введите его.' : 'Код пришёл в Telegram этого аккаунта (сообщение от «Telegram»).'}</div>
      <div class="row2"><input class="field" id="tgCode" type="${isPw ? 'password' : 'text'}" inputmode="${isPw ? 'text' : 'numeric'}" placeholder="${isPw ? 'Облачный пароль' : 'Код из Telegram'}" style="flex:1">
      <button class="btn primary" id="tgLogin" data-pw="${isPw ? 1 : ''}">Войти</button><button class="btn ghost" id="tgRestart">Заново</button></div>`;
  } else {
    tgAccount = `<div class="row2"><input class="field" id="tgPhone" placeholder="+7 999 123-45-67" style="flex:1" ${tg.fields.api_hash.set ? '' : 'disabled'}>
      <button class="btn" id="tgSend" ${tg.fields.api_hash.set ? '' : 'disabled'}>Получить код</button></div>
      ${tg.fields.api_hash.set ? '' : '<div class="mut small">Сначала сохраните api_id и api_hash</div>'}`;
  }

  $('integrations').innerHTML = `<div class="ints">
    <div class="card int" data-src="instagram">
      ${intHead('instagram', ig)}
      ${intField('user_id', ig.fields.user_id, 'ID аккаунта Instagram', {hint: 'Цифры рядом с аккаунтом в блоке «Создание маркеров доступа» (обычно начинаются с 1784…)'})}
      ${intField('access_token', ig.fields.access_token, 'Маркер доступа (токен)', {hint: 'Действует 60 дней, потом создайте новый и вставьте сюда'})}
      ${intField('since', ig.fields.since, 'Собирать рилс начиная с', {type: 'date'})}
      <div class="row2"><button class="btn primary" data-save="instagram">Сохранить</button>
        <button class="btn" data-sync="instagram" ${ig.enabled ? '' : 'disabled'}>Проверить и обновить</button></div>
    </div>

    <div class="card int" data-src="telegram">
      ${intHead('telegram', tg)}
      <div class="step">1. Ключи с my.telegram.org</div>
      ${intField('api_id', tg.fields.api_id, 'api_id', {placeholder: 'Цифры'})}
      ${intField('api_hash', tg.fields.api_hash, 'api_hash')}
      <div class="row2"><button class="btn" data-save="telegram" data-only="api_id,api_hash">Сохранить ключи</button></div>
      <div class="step">2. Аккаунт</div>
      <div class="mut small">Отдельный аккаунт, подписанный на оба канала. Без прав админа — иначе админка откажется с ним работать.</div>
      ${tgAccount}
      <div class="step">3. Каналы</div>
      ${chSel('open_channel', 'Открытый канал')}
      ${chSel('closed_channel', 'Закрытый канал')}
      ${intField('since', tg.fields.since, 'Собирать посты начиная с', {type: 'date'})}
      <div class="row2"><button class="btn" id="tgLoad" ${tg.logged_in ? '' : 'disabled'}>Загрузить список каналов</button>
        <button class="btn primary" data-save="telegram" data-only="open_channel,closed_channel,since">Сохранить каналы</button>
        <button class="btn" data-sync="telegram" ${tg.enabled ? '' : 'disabled'}>Проверить и обновить</button></div>
    </div>

    <div class="card int" data-src="getcourse">
      ${intHead('getcourse', gc)}
      ${intField('domain', gc.fields.domain, 'Адрес школы', {placeholder: 'school.dari-malakhovskaya.ru'})}
      ${intField('api_key', gc.fields.api_key, 'Ключ API', {hint: 'Если GetCourse даёт выбор — ключ «только для чтения»'})}
      ${intField('since', gc.fields.since, 'Загружать заказы начиная с', {type: 'date'})}
      <div class="row2"><button class="btn primary" data-save="getcourse">Сохранить</button>
        <button class="btn" data-sync="getcourse" ${gc.enabled ? '' : 'disabled'}>Проверить и обновить</button></div>
      <div class="step">Вебхук (необязательно)</div>
      <div style="margin-top:6px">${hook}</div>
      <div class="row2"><button class="btn ghost" id="gcHook">${gc.webhook_token ? 'Заменить токен' : 'Создать токен'}</button></div>
    </div>

    <div class="card int">
      <h3>Обновление по расписанию</h3>
      <p class="mut small" style="margin:0 0 8px">Vercel запускает сбор раз в день. Сторис живут 24 часа, поэтому добавьте на cron-job.org задание раз в час на этот адрес:</p>
      <code>${esc(base)}/api/cron?key=${esc(r.cron_key || '')}</code>
      <div class="row2"><button class="btn ghost" data-copy="${esc(base)}/api/cron?key=${esc(r.cron_key || '')}">Копировать</button></div>
    </div>
  </div>`;

  const root = $('integrations');
  const reload = async res => renderIntegrations(res || await api('/api/integrations'));
  root.querySelectorAll('[data-save]').forEach(b => b.onclick = async () => {
    const card = b.closest('[data-src]'), src = b.dataset.save;
    const only = b.dataset.only ? b.dataset.only.split(',') : null;
    const body = {};
    card.querySelectorAll('[data-k]').forEach(i => { if (!only || only.includes(i.dataset.k)) body[i.dataset.k] = i.value; });
    if (!only || only.includes('open_channel')) body.enabled = true;
    try { await reload(await api(`/api/integrations/${src}`, {method: 'PUT', body})); toast('Сохранено'); } catch (e) { fail(e); }
  });
  root.querySelectorAll('[data-enable]').forEach(c => c.onchange = async () => {
    try { await reload(await api(`/api/integrations/${c.dataset.enable}`, {method: 'PUT', body: {enabled: c.checked}})); } catch (e) { fail(e); }
  });
  root.querySelectorAll('[data-sync]').forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = 'Обновляю…';
    try { const x = await api(`/api/sync/${b.dataset.sync}`, {method: 'POST'}); toast(x.message); } catch (e) { fail(e); }
    setTimeout(() => reload().catch(fail), 1500);
  });
  root.querySelectorAll('[data-copy]').forEach(b => b.onclick = () =>
    navigator.clipboard.writeText(b.dataset.copy).then(() => toast('Скопировано'), () => toast(b.dataset.copy)));
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on('gcHook', async () => {
    if (r.sources.getcourse.webhook_token && !confirm('Старый адрес вебхука перестанет работать. Заменить?')) return;
    try { await reload(await api('/api/integrations/getcourse', {method: 'PUT', body: {new_webhook_token: true}})); } catch (e) { fail(e); }
  });
  on('tgSend', async () => {
    try { const x = await api('/api/telegram/code', {method: 'POST', body: {phone: $('tgPhone').value}}); toast(x.message); await reload(); } catch (e) { fail(e); }
  });
  on('tgLogin', async () => {
    const pw = $('tgLogin').dataset.pw;
    try {
      const x = await api('/api/telegram/login', {method: 'POST', body: pw ? {password: $('tgCode').value} : {code: $('tgCode').value}});
      if (x.message) toast(x.message);
      await reload();
    } catch (e) { fail(e); }
  });
  on('tgRestart', async () => { try { await api('/api/telegram/logout', {method: 'POST'}); await reload(); } catch (e) { fail(e); } });
  on('tgLogout', async () => {
    if (!confirm('Отключить аккаунт Telegram от админки?')) return;
    try { await api('/api/telegram/logout', {method: 'POST'}); await reload(); } catch (e) { fail(e); }
  });
  on('tgLoad', async () => {
    $('tgLoad').disabled = true; $('tgLoad').textContent = 'Загружаю…';
    try {
      const {channels} = await api('/api/telegram/channels');
      root.querySelectorAll('[data-src="telegram"] select[data-k]').forEach(sel => {
        const cur = sel.value;
        sel.innerHTML = '<option value="">— не выбран —</option>' + channels.map(c =>
          `<option value="${esc(c.ref)}" ${c.admin ? 'disabled' : ''} ${c.ref === cur ? 'selected' : ''}>${esc(c.title)}${c.admin ? ' — вы админ, нельзя' : ''}</option>`).join('');
      });
      toast(channels.length ? `Каналов: ${channels.length}. Выберите и сохраните` : 'Аккаунт не подписан ни на один канал');
    } catch (e) { fail(e); }
    $('tgLoad').disabled = false; $('tgLoad').textContent = 'Загрузить список каналов';
  });
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
