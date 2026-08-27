const main = document.getElementById('main');
const nav = document.getElementById('nav');
const views = {};
let runtimeReady = false;
let teacherAuthenticated = false;
let lockButton = null;
let lockFeedback = null;
let currentPinInput = null;

nav.setAttribute('aria-busy', 'true');
nav.querySelectorAll('button').forEach(button => { button.disabled = true; });

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) for (const key in attrs) {
    if (key === 'onclick') node.addEventListener('click', attrs[key]);
    else if (key === 'oninput') node.addEventListener('input', attrs[key]);
    else if (key === 'onchange') node.addEventListener('change', attrs[key]);
    else if (key === 'style') node.style.cssText = attrs[key];
    else node.setAttribute(key, attrs[key]);
  }
  for (const child of children) node.append(child);
  return node;
}

function api(path, options) { return window.DuckAPI.request(path, options); }

function clearTeacherPin() {
  if (currentPinInput) currentPinInput.value = '';
  currentPinInput = null;
}

function updateTeacherNavigation() {
  const enabled = runtimeReady && teacherAuthenticated;
  if (!enabled) {
    nav.setAttribute('aria-busy', 'true');
    nav.querySelectorAll('button').forEach(button => { button.disabled = true; });
    return;
  }
  nav.removeAttribute('aria-busy');
  nav.querySelectorAll('button').forEach(button => { button.disabled = false; });
}

function renderTeacherLocked(message) {
  main.replaceChildren();
  const card = h('section', { class: 'card', role: 'status' });
  card.append(h('h2', null, '教师端已锁定'), h('p', { class: 'muted' }, message));
  main.append(card);
}

function setLockFeedback(message) {
  if (!lockFeedback) {
    lockFeedback = h('p', {
      id: 'teacher-lock-feedback',
      class: 'teacher-lock-feedback',
      role: 'alert',
      'aria-live': 'assertive',
    });
    document.querySelector('aside').append(lockFeedback);
  }
  lockFeedback.textContent = message;
}

function ensureLockButton() {
  if (lockButton) return;
  lockButton = h('button', { class: 'btn gray teacher-lock-button', type: 'button' }, '立即锁定');
  lockButton.addEventListener('click', lockTeacherPage);
  document.querySelector('aside').append(lockButton);
}

function authenticationErrorCopy(error) {
  return error && error.code === 'PIN_INVALID' ? 'PIN 不正确' : '暂时无法完成教师验证，请稍后重试。';
}

async function bootstrapTeacherPage() {
  await window.DuckAPI.ready();
  runtimeReady = true;
  updateTeacherNavigation();
  await unlockTeacherPage();
  restoreTeacherRoute();
}

async function unlockTeacherPage() {
  const auth = await window.DuckAuth.status();
  if (auth.authenticated) {
    teacherAuthenticated = true;
    updateTeacherNavigation();
    ensureLockButton();
    lockButton.disabled = false;
    return;
  }

  teacherAuthenticated = false;
  updateTeacherNavigation();
  return new Promise((resolve) => {
    main.replaceChildren();
    const form = h('form', { class: 'card' });
    const inputId = 'teacher-pin';
    const label = h('label', { for: inputId }, auth.configured ? '教师 PIN' : '设置教师 PIN');
    const input = h('input', {
      id: inputId,
      type: 'password',
      inputmode: 'numeric',
      pattern: '[0-9]{4,6}',
      minlength: '4',
      maxlength: '6',
      autocomplete: 'off',
      required: 'required',
    });
    currentPinInput = input;
    const feedback = h('p', { role: 'alert', 'aria-live': 'assertive' });
    const submit = h('button', { class: 'btn', type: 'submit' }, auth.configured ? '解锁' : '设置并解锁');
    form.append(
      h('h2', null, auth.configured ? '教师端已锁定' : '首次设置教师 PIN'),
      label,
      input,
      submit,
      feedback,
    );
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      submit.disabled = true;
      feedback.textContent = '';
      try {
        if (auth.configured) await window.DuckAuth.unlock(input.value);
        else await window.DuckAuth.setup(input.value);
        clearTeacherPin();
        form.remove();
        teacherAuthenticated = true;
        updateTeacherNavigation();
        ensureLockButton();
        lockButton.disabled = false;
        resolve();
      } catch (error) {
        feedback.textContent = authenticationErrorCopy(error);
        submit.disabled = false;
        input.focus();
      }
    });
    main.append(form);
    input.focus();
  });
}

function clearTeacherViews() {
  Object.values(views).forEach((view) => view.remove());
  for (const key of Object.keys(views)) delete views[key];
}

function restoreTeacherRoute() {
  routeFromHash();
  if (!location.hash) show('overview');
}

function handleTeacherBootstrapFailure(_error) {
  if (document.getElementById('runtime-maintenance')) return;
  teacherAuthenticated = false;
  updateTeacherNavigation();
  renderTeacherLocked('教师端暂不可用，请稍后重试。');
}

async function lockTeacherPage() {
  lockButton.disabled = true;
  setLockFeedback('');
  try {
    await window.DuckAuth.lock();
    clearTeacherPin();
    teacherAuthenticated = false;
    updateTeacherNavigation();
    clearTeacherViews();
    lockButton.remove();
    lockButton = null;
    renderTeacherLocked('教师端已锁定，重新输入 PIN 后可继续。');
    await unlockTeacherPage();
    restoreTeacherRoute();
  } catch (_error) {
    lockButton.disabled = false;
    setLockFeedback('暂时无法锁定，请稍后重试。');
  }
}

nav.addEventListener('click', event => {
  if (!runtimeReady || !teacherAuthenticated) return;
  const button = event.target.closest('button');
  if (!button) return;
  document.querySelectorAll('#nav button').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  show(button.dataset.v);
});

function show(name) {
  if (!runtimeReady || !teacherAuthenticated) return;
  Object.values(views).forEach(view => view.classList.remove('active'));
  if (!views[name]) {
    views[name] = buildView(name);
    main.appendChild(views[name]);
  }
  views[name].classList.add('active');
}

function buildView(name) {
  const view = h('div', { class: 'view' });
  const fns = { overview, children, ducks, roster, review, growth, search };
  fns[name](view);
  return view;
}

function overview(view) {
  view.append(h('h2', null, '概览'));
  const metrics = h('div', { class: 'metrics' });
  view.append(metrics);
  api('/api/analysis/overview').then(rows => {
    const total = rows.length;
    const conversations = rows.reduce((sum, row) => sum + row.conversations, 0);
    const assessed = rows.filter(row => row.latest_overall != null).length;
    metrics.innerHTML = '';
    metrics.append(
      metric(total, '幼儿人数'), metric(conversations, '累计会话'), metric(assessed, '已评估'),
      metric(rows.reduce((sum, row) => sum + (row.latest_overall || 0), 0) / (assessed || 1), '平均综合分'),
    );
  });
  view.append(h('div', { class: 'card' }, h('div', { class: 'muted' }, '从左侧导航进入各功能模块。日常流程：值日排班 → 幼儿端对话 → 值日审阅确认评估 → 查看成长曲线。')));
}

function metric(num, label) {
  const value = typeof num === 'number' ? (Math.round(num * 100) / 100) : num;
  return h('div', { class: 'card metric' }, h('div', { class: 'num' }, String(value)), h('div', { class: 'label' }, label));
}

function children(view) {
  view.append(h('h2', null, '幼儿管理'));
  const form = h('div', { class: 'row card' });
  const nameIn = h('input', { placeholder: '全名' });
  const nickIn = h('input', { placeholder: '小名（选填）' });
  form.append(nameIn, nickIn, h('button', { class: 'btn', onclick: () => {
    api('/api/children', { method: 'POST', body: { name: nameIn.value, nickname: nickIn.value } }).then(() => { nameIn.value = nickIn.value = ''; reload(); });
  } }, '添加幼儿'));
  view.append(form);
  const table = h('table');
  view.append(h('div', { class: 'card' }, table));
  function reload() {
    api('/api/children').then(rows => {
      table.innerHTML = '';
      table.append(h('tr', null, th('ID'), th('全名'), th('小名'), th('状态'), th('操作')));
      rows.forEach(child => {
        const row = h('tr');
        row.append(td(child.id), td(child.name), td(child.nickname || '-'), td(child.active ? '在园' : '离园'),
          td(h('button', { class: 'btn small gray', onclick: () => api('/api/children/' + child.id, { method: 'DELETE' }).then(reload) }, '删除')));
        table.append(row);
      });
    });
  }
  reload();
}

function th(text) { return h('th', null, text); }
function td(...children) { const node = h('td'); children.forEach(child => node.append(child)); return node; }

function ducks(view) {
  view.append(h('h2', null, '小鸭管理'));
  const form = h('div', { class: 'row card' });
  const nameIn = h('input', { placeholder: '小鸭名字' });
  const statusIn = h('input', { placeholder: '状态（如：活泼健康）' });
  form.append(nameIn, statusIn, h('button', { class: 'btn', onclick: () => {
    api('/api/ducks', { method: 'POST', body: { name: nameIn.value, status: statusIn.value } }).then(() => { nameIn.value = statusIn.value = ''; reload(); });
  } }, '添加小鸭'));
  view.append(form);
  const table = h('table');
  view.append(h('div', { class: 'card' }, table));
  function reload() {
    api('/api/ducks').then(rows => {
      table.innerHTML = '';
      table.append(h('tr', null, th('ID'), th('名字'), th('状态'), th('档案'), th('操作')));
      rows.forEach(duck => {
        const row = h('tr');
        row.append(td(duck.id), td(duck.name), td(duck.status || '-'),
          td(h('button', { class: 'btn small gray', onclick: () => summarizeDuck(duck) }, '生成档案')),
          td(h('button', { class: 'btn small gray', onclick: () => api('/api/ducks/' + duck.id, { method: 'DELETE' }).then(reload) }, '删除')));
        table.append(row);
      });
    });
  }
  function summarizeDuck(duck) {
    api('/api/ducks/' + duck.id + '/summarize', { method: 'POST' }).then(result => alert('「' + duck.name + '」档案：\n' + (result.summary || '（暂无足够记录）')));
  }
  reload();
}

function roster(view) {
  view.append(h('h2', null, '值日排班'));
  const autoCard = h('div', { class: 'card' });
  const startIn = h('input', { type: 'date' });
  const daysIn = h('input', { type: 'number', value: 10, class: 'teacher-days' });
  const cycleIn = h('input', { placeholder: '周期（如 第1周）', value: '第1周' });
  autoCard.append(h('div', { class: 'row' }, h('b', null, '自动轮值：'), '开始日期', startIn, '天数', daysIn, '周期', cycleIn,
    h('button', { class: 'btn', onclick: () => {
      api('/api/roster/auto', { method: 'POST', body: { start_date: startIn.value, days: +daysIn.value, cycle: cycleIn.value } }).then(() => reload());
    } }, '生成排班')));
  view.append(autoCard);
  const manualCard = h('div', { class: 'card' });
  const dateIn = h('input', { type: 'date' });
  const cycle2 = h('input', { placeholder: '周期', value: '第1周' });
  const selBox = h('div', { class: 'row' });
  const chosen = [];
  manualCard.append(h('div', { class: 'row' }, '手动指定：日期', dateIn, '周期', cycle2, h('button', { class: 'btn green', onclick: () => {
    if (chosen.length !== 2) return alert('请选择 2 名幼儿');
    api('/api/roster', { method: 'POST', body: { cycle: cycle2.value, date: dateIn.value, child_ids: chosen } }).then(() => reload());
  } }, '保存当日排班')));
  manualCard.append(h('div', { class: 'muted' }, '点击幼儿卡片选择 2 名值日幼儿：'));
  manualCard.append(selBox);
  api('/api/children').then(rows => {
    rows.forEach(child => {
      const button = h('button', { class: 'btn gray small', onclick: () => {
        const index = chosen.indexOf(child.id);
        if (index >= 0) { chosen.splice(index, 1); button.classList.remove('on'); button.style.background = ''; }
        else { if (chosen.length >= 2) return alert('最多 2 名'); chosen.push(child.id); button.classList.add('on'); button.style.background = '#ffb800'; }
      } }, child.nickname || child.name);
      selBox.append(button);
    });
  });
  view.append(manualCard);
  const table = h('table');
  view.append(h('div', { class: 'card' }, table));
  function reload() {
    api('/api/roster').then(rows => {
      api('/api/children').then(children => {
        const map = Object.fromEntries(children.map(child => [child.id, child.nickname || child.name]));
        const byDate = {};
        rows.forEach(row => { (byDate[row.date] = byDate[row.date] || []).push(row); });
        table.innerHTML = '';
        table.append(h('tr', null, th('日期'), th('周期'), th('值日幼儿')));
        Object.keys(byDate).sort().forEach(date => {
          table.append(h('tr', null, td(date), td(byDate[date][0].cycle), td(byDate[date].map(row => map[row.child_id] || row.child_id).join('、'))));
        });
      });
    });
  }
  reload();
}

function review(view) {
  view.append(h('h2', null, '值日审阅'));
  const list = h('div');
  const detail = h('div');
  view.append(list, detail);
  api('/api/conversations').then(rows => {
    list.innerHTML = '';
    const table = h('table');
    table.append(h('tr', null, th('ID'), th('日期'), th('状态'), th('结束原因'), th('操作')));
    rows.forEach(conversation => {
      const reasonMap = { max_rounds: '达到轮次', complete: '信息充分', manual: '手动结束' };
      table.append(h('tr', null, td(conversation.id), td(conversation.date), td(conversation.status), td(reasonMap[conversation.end_reason] || conversation.end_reason || '-'),
        td(h('button', { class: 'btn small', onclick: () => openDetail(conversation.id) }, '审阅'))));
    });
    list.append(h('div', { class: 'card' }, table));
  });
  function openDetail(conversationId) {
    api('/api/conversations/' + conversationId).then(data => {
      detail.innerHTML = '';
      const card = h('div', { class: 'card' });
      card.append(h('h2', null, '会话 #' + data.id + ' 详情'), h('b', null, '对话记录'));
      const messages = h('div', { class: 'teacher-scroll' });
      data.messages.forEach(message => messages.append(h('div', { class: 'bubble ' + (message.role === 'child' ? 'c' : 'd') }, (message.role === 'child' ? '幼儿：' : '日记本：') + message.text)));
      card.append(messages, h('b', null, '饲养流水（可修正）'));
      const logsBox = h('div');
      (data.feeding_logs || []).forEach(log => {
        const category = h('select');
        ['喂食', '清洁', '观察', '其它'].forEach(item => category.append(new Option(item, item)));
        category.value = log.category;
        const content = h('input', { value: log.content, class: 'teacher-flex' });
        logsBox.append(h('div', { class: 'row' }, category, content));
      });
      card.append(logsBox, h('b', null, '情绪'));
      const emotion = h('select');
      ['开心', '平静', '疲惫', '期待', '其它'].forEach(item => emotion.append(new Option(item, item)));
      if (data.emotion) emotion.value = data.emotion.emotion;
      const intensity = h('input', { type: 'number', min: 1, max: 5, value: data.emotion ? data.emotion.intensity : 3, class: 'teacher-narrow' });
      card.append(h('div', { class: 'row teacher-row-top' }, '情绪', emotion, '强度(1-5)', intensity));
      const scoreState = {};
      if (data.assessment) {
        card.append(h('b', null, '能力评估（可调整后确认）'));
        const scoreBox = h('div');
        data.assessment.scores.forEach(score => {
          scoreState[score.dimension_id] = score.score;
          const name = h('span', { class: 'name' }, score.dimension_name);
          const stars = h('div', { class: 'stars' });
          const reason = h('textarea', { placeholder: '评分理由（引用对话原句）' });
          reason.value = score.reason || '';
          const row = h('div', { class: 'score-box' }, name);
          for (let value = 1; value <= 5; value++) {
            const star = h('button', { onclick: () => { scoreState[score.dimension_id] = value; renderStars(); } }, '★');
            stars.append(star);
          }
          function renderStars() { [...stars.children].forEach((star, index) => star.classList.toggle('on', index < scoreState[score.dimension_id])); }
          renderStars();
          row.append(stars);
          scoreBox.append(row, reason);
        });
        card.append(scoreBox, h('div', { class: 'row teacher-row-actions' },
          h('button', { class: 'btn', onclick: () => saveReview(conversationId, data) }, '保存修正'),
          h('button', { class: 'btn green', onclick: () => confirmAssessment(conversationId, data) }, '确认评估'),
        ));
        function saveReview(id, source) {
          const body = {
            feeding_logs: source.feeding_logs.map((log, index) => ({ id: log.id, category: logsBox.children[index].children[0].value, content: logsBox.children[index].children[1].value })),
            emotion: { emotion: emotion.value, intensity: +intensity.value },
          };
          api('/api/conversations/' + id + '/logs', { method: 'PATCH', body }).then(() => alert('已保存修正'));
        }
        function confirmAssessment(id, source) {
          const scores = {};
          Object.keys(scoreState).forEach(key => { scores[key] = { score: scoreState[key] }; });
          api('/api/assessments/' + source.assessment.id + '/confirm', { method: 'POST', body: { scores } }).then(() => { alert('评估已确认'); openDetail(id); });
        }
      }
      detail.append(card);
    });
  }
}

function growth(view) {
  view.append(h('h2', null, '能力成长曲线'));
  const select = h('select');
  select.append(new Option('— 选择幼儿 —', ''));
  const wrap = h('div');
  view.append(h('div', { class: 'row' }, select), wrap);
  const params = new URLSearchParams(location.search);
  let childId = params.get('child_id');
  if (!childId && location.hash.includes('?')) childId = new URLSearchParams(location.hash.split('?')[1] || '').get('child_id');
  api('/api/children').then(rows => {
    rows.forEach(child => select.append(new Option(child.nickname || child.name, child.id)));
    if (childId) select.value = childId;
  });
  if (childId) api('/api/analysis/growth?child_id=' + childId).then(data => drawGrowth(wrap, data));
  select.addEventListener('change', () => {
    if (!select.value) return;
    api('/api/analysis/growth?child_id=' + select.value).then(data => drawGrowth(wrap, data));
  });
}

function drawGrowth(wrap, data) {
  wrap.innerHTML = '';
  const dimensions = data.dimensions.filter(item => item.points.length);
  if (!dimensions.length) { wrap.append(h('div', { class: 'card muted' }, '暂无已确认的评估数据')); return; }
  const colors = ['#2f80ed', '#16a34a', '#f59e0b', '#8b5cf6', '#ef4444'];
  const width = 760, height = 320, padding = 48;
  const allDates = [...new Set(dimensions.flatMap(item => item.points.map(point => point.date)))].sort();
  const x = index => allDates.length === 1 ? width / 2 : padding + index * (width - 2 * padding) / (allDates.length - 1);
  const y = score => height - padding - (score - 1) * (height - 2 * padding) / 4;
  let svg = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">`;
  for (let score = 1; score <= 5; score++) svg += `<line x1="${padding}" y1="${y(score)}" x2="${width - padding}" y2="${y(score)}" stroke="#e5e7eb" stroke-width="1"/><text x="${padding - 8}" y="${y(score) + 4}" text-anchor="end" font-size="11" fill="#9ca3af">${score}分</text>`;
  allDates.forEach((date, index) => { svg += `<text x="${x(index)}" y="${height - padding + 18}" text-anchor="middle" font-size="11" fill="#9ca3af">${date}</text>`; });
  dimensions.forEach((dimension, dimensionIndex) => {
    const points = dimension.points.map(point => ({ x: x(allDates.indexOf(point.date)), y: y(point.score) }));
    const path = points.map((point, index) => (index ? 'L' : 'M') + point.x + ',' + point.y).join(' ');
    svg += `<path d="${path}" fill="none" stroke="${colors[dimensionIndex % colors.length]}" stroke-width="2.5"/>`;
    points.forEach(point => { svg += `<circle cx="${point.x}" cy="${point.y}" r="4" fill="${colors[dimensionIndex % colors.length]}"/>`; });
  });
  svg += '</svg>';
  const legend = h('div', { class: 'row teacher-row-top' });
  dimensions.forEach((dimension, index) => {
    const item = h('span', { class: 'muted' }, '● ' + dimension.name + '  ');
    item.style.color = colors[index % colors.length];
    legend.append(item);
  });
  const chart = h('div', { class: 'card chart-wrap teacher-chart' });
  chart.innerHTML = `<div class="teacher-chart-inner">${svg}</div>`;
  wrap.append(chart, legend);
}

function search(view) {
  view.append(h('h2', null, '明细检索'));
  const childSelect = h('select');
  childSelect.append(new Option('全部幼儿', ''));
  const box = h('div');
  view.append(h('div', { class: 'row' }, childSelect), box);
  api('/api/children').then(rows => rows.forEach(child => childSelect.append(new Option(child.nickname || child.name, child.id))));
  childSelect.addEventListener('change', load);
  function load() {
    const query = childSelect.value ? '?child_id=' + childSelect.value : '';
    api('/api/conversations' + query).then(rows => {
      box.innerHTML = '';
      if (!rows.length) { box.append(h('div', { class: 'card muted' }, '暂无记录')); return; }
      const table = h('table');
      table.append(h('tr', null, th('会话'), th('日期'), th('结束原因'), th('操作')));
      rows.forEach(conversation => table.append(h('tr', null, td(conversation.id), td(conversation.date), td(conversation.end_reason || '-'), td(h('button', { class: 'btn small', onclick: () => showConversation(conversation.id) }, '查看')))));
      box.append(h('div', { class: 'card' }, table));
    });
  }
  function showConversation(id) {
    api('/api/conversations/' + id).then(data => {
      box.innerHTML = '';
      const card = h('div', { class: 'card' });
      card.append(h('b', null, '会话 #' + id));
      data.messages.forEach(message => card.append(h('div', { class: 'bubble ' + (message.role === 'child' ? 'c' : 'd') }, (message.role === 'child' ? '幼儿：' : '日记本：') + message.text)));
      if (data.feeding_logs.length) card.append(h('div', { class: 'muted teacher-detail-top' }, '饲养流水：' + data.feeding_logs.map(log => log.category + '·' + log.content).join('；')));
      if (data.emotion) card.append(h('div', { class: 'muted' }, '情绪：' + data.emotion.emotion + '（强度 ' + data.emotion.intensity + '）'));
      box.append(card);
    });
  }
  load();
}

function routeFromHash() {
  const view = location.hash.replace('#', '').split('?')[0];
  if (view && ['overview', 'children', 'ducks', 'roster', 'review', 'growth', 'search'].includes(view)) show(view);
}

window.addEventListener('hashchange', routeFromHash);
window.addEventListener('pagehide', clearTeacherPin, { once: false });
bootstrapTeacherPage().catch(handleTeacherBootstrapFailure);
