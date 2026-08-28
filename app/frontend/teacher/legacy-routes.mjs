const FAILURE_COPY = '加载失败，请重新进入此页面。';

function createElement(document, tag, attrs, ...children) {
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

function tableHeading(document, text) {
  return createElement(document, 'th', null, text);
}

function tableCell(document, ...children) {
  const node = createElement(document, 'td');
  children.forEach(child => node.append(child));
  return node;
}

function beginRoute(document, request, context, title) {
  const view = createElement(document, 'div', { class: 'view active' });
  view.append(createElement(document, 'h2', null, title));
  context.root.replaceChildren(view);
  let alertNode = null;
  const failed = () => {
    if (!context.isCurrent() || context.signal.aborted) return;
    if (!alertNode) {
      alertNode = createElement(document, 'p', { class: 'teacher-route-error', role: 'alert' }, FAILURE_COPY);
      view.append(alertNode);
    }
  };
  const scopedRequest = (path, options, onSuccess) => {
    const requestOptions = { ...(options || {}), signal: context.signal };
    const work = Promise.resolve()
      .then(() => request(path, requestOptions))
      .then(result => {
        if (!context.isCurrent() || context.signal.aborted) return;
        onSuccess(result);
      })
      .catch(error => {
        if (!context.isCurrent() || context.signal.aborted || error?.name === 'AbortError') return;
        failed();
      });
    return work;
  };
  return { view, scopedRequest };
}

function drawGrowth(document, wrap, data) {
  wrap.innerHTML = '';
  const dimensions = data.dimensions.filter(item => item.points.length);
  if (!dimensions.length) {
    wrap.append(createElement(document, 'div', { class: 'card muted' }, '暂无已确认的评估数据'));
    return;
  }
  const colors = ['#2f80ed', '#16a34a', '#f59e0b', '#8b5cf6', '#ef4444'];
  const width = 760;
  const height = 320;
  const padding = 48;
  const allDates = [...new Set(dimensions.flatMap(item => item.points.map(point => point.date)))].sort();
  const x = index => allDates.length === 1 ? width / 2 : padding + index * (width - 2 * padding) / (allDates.length - 1);
  const y = score => height - padding - (score - 1) * (height - 2 * padding) / 4;
  let svg = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">`;
  for (let score = 1; score <= 5; score += 1) {
    svg += `<line x1="${padding}" y1="${y(score)}" x2="${width - padding}" y2="${y(score)}" stroke="#e5e7eb" stroke-width="1"/><text x="${padding - 8}" y="${y(score) + 4}" text-anchor="end" font-size="11" fill="#9ca3af">${score}分</text>`;
  }
  allDates.forEach((date, index) => { svg += `<text x="${x(index)}" y="${height - padding + 18}" text-anchor="middle" font-size="11" fill="#9ca3af">${date}</text>`; });
  dimensions.forEach((dimension, dimensionIndex) => {
    const points = dimension.points.map(point => ({ x: x(allDates.indexOf(point.date)), y: y(point.score) }));
    const path = points.map((point, index) => `${index ? 'L' : 'M'}${point.x},${point.y}`).join(' ');
    svg += `<path d="${path}" fill="none" stroke="${colors[dimensionIndex % colors.length]}" stroke-width="2.5"/>`;
    points.forEach(point => { svg += `<circle cx="${point.x}" cy="${point.y}" r="4" fill="${colors[dimensionIndex % colors.length]}"/>`; });
  });
  svg += '</svg>';
  const legend = createElement(document, 'div', { class: 'row teacher-row-top' });
  dimensions.forEach((dimension, index) => {
    const item = createElement(document, 'span', { class: 'muted' }, `● ${dimension.name}  `);
    item.style.color = colors[index % colors.length];
    legend.append(item);
  });
  const chart = createElement(document, 'div', { class: 'card chart-wrap teacher-chart' });
  chart.innerHTML = `<div class="teacher-chart-inner">${svg}</div>`;
  wrap.append(chart, legend);
}

export function createLegacyTeacherRoutes({ request, document, alert }) {
  if (typeof request !== 'function' || !document?.createElement || typeof alert !== 'function') {
    throw new TypeError('Legacy teacher routes require request, document, and alert dependencies.');
  }

  function children(context) {
    const { view, scopedRequest } = beginRoute(document, request, context, '幼儿管理');
    const form = createElement(document, 'div', { class: 'row card' });
    const nameInput = createElement(document, 'input', { placeholder: '全名' });
    const nicknameInput = createElement(document, 'input', { placeholder: '小名（选填）' });
    const table = createElement(document, 'table');
    const reload = () => scopedRequest('/api/children', {}, rows => {
      table.innerHTML = '';
      table.append(createElement(document, 'tr', null,
        tableHeading(document, 'ID'), tableHeading(document, '全名'), tableHeading(document, '小名'), tableHeading(document, '状态'), tableHeading(document, '操作')));
      rows.forEach(child => {
        const row = createElement(document, 'tr');
        const remove = createElement(document, 'button', { class: 'btn small gray', onclick: () => {
          scopedRequest('/api/children/' + child.id, { method: 'DELETE' }, reload);
        } }, '删除');
        row.append(tableCell(document, child.id), tableCell(document, child.name), tableCell(document, child.nickname || '-'),
          tableCell(document, child.active ? '在园' : '离园'), tableCell(document, remove));
        table.append(row);
      });
    });
    form.append(nameInput, nicknameInput, createElement(document, 'button', { class: 'btn', onclick: () => {
      scopedRequest('/api/children', { method: 'POST', body: { name: nameInput.value, nickname: nicknameInput.value } }, () => {
        nameInput.value = '';
        nicknameInput.value = '';
        reload();
      });
    } }, '添加幼儿'));
    view.append(form, createElement(document, 'div', { class: 'card' }, table));
    reload();
  }

  function ducks(context) {
    const { view, scopedRequest } = beginRoute(document, request, context, '小鸭管理');
    const form = createElement(document, 'div', { class: 'row card' });
    const nameInput = createElement(document, 'input', { placeholder: '小鸭名字' });
    const statusInput = createElement(document, 'input', { placeholder: '状态（如：活泼健康）' });
    const table = createElement(document, 'table');
    const reload = () => scopedRequest('/api/ducks', {}, rows => {
      table.innerHTML = '';
      table.append(createElement(document, 'tr', null,
        tableHeading(document, 'ID'), tableHeading(document, '名字'), tableHeading(document, '状态'), tableHeading(document, '档案'), tableHeading(document, '操作')));
      rows.forEach(duck => {
        const summarize = createElement(document, 'button', { class: 'btn small gray', onclick: () => {
          scopedRequest('/api/ducks/' + duck.id + '/summarize', { method: 'POST' }, result => {
            alert(`「${duck.name}」档案：\n${result.summary || '（暂无足够记录）'}`);
          });
        } }, '生成档案');
        const remove = createElement(document, 'button', { class: 'btn small gray', onclick: () => {
          scopedRequest('/api/ducks/' + duck.id, { method: 'DELETE' }, reload);
        } }, '删除');
        table.append(createElement(document, 'tr', null,
          tableCell(document, duck.id), tableCell(document, duck.name), tableCell(document, duck.status || '-'),
          tableCell(document, summarize), tableCell(document, remove)));
      });
    });
    form.append(nameInput, statusInput, createElement(document, 'button', { class: 'btn', onclick: () => {
      scopedRequest('/api/ducks', { method: 'POST', body: { name: nameInput.value, status: statusInput.value } }, () => {
        nameInput.value = '';
        statusInput.value = '';
        reload();
      });
    } }, '添加小鸭'));
    view.append(form, createElement(document, 'div', { class: 'card' }, table));
    reload();
  }

  function roster(context) {
    const { view, scopedRequest } = beginRoute(document, request, context, '值日排班');
    const autoCard = createElement(document, 'div', { class: 'card' });
    const startInput = createElement(document, 'input', { type: 'date' });
    const daysInput = createElement(document, 'input', { type: 'number', value: 10, class: 'teacher-days' });
    const cycleInput = createElement(document, 'input', { placeholder: '周期（如 第1周）', value: '第1周' });
    const manualCard = createElement(document, 'div', { class: 'card' });
    const dateInput = createElement(document, 'input', { type: 'date' });
    const manualCycleInput = createElement(document, 'input', { placeholder: '周期', value: '第1周' });
    const choices = createElement(document, 'div', { class: 'row' });
    const chosen = [];
    const table = createElement(document, 'table');
    const reload = () => scopedRequest('/api/roster', {}, rows => {
      scopedRequest('/api/children', {}, childrenRows => {
        const names = Object.fromEntries(childrenRows.map(child => [child.id, child.nickname || child.name]));
        const byDate = {};
        rows.forEach(row => { (byDate[row.date] = byDate[row.date] || []).push(row); });
        table.innerHTML = '';
        table.append(createElement(document, 'tr', null, tableHeading(document, '日期'), tableHeading(document, '周期'), tableHeading(document, '值日幼儿')));
        Object.keys(byDate).sort().forEach(date => {
          table.append(createElement(document, 'tr', null,
            tableCell(document, date), tableCell(document, byDate[date][0].cycle),
            tableCell(document, byDate[date].map(row => names[row.child_id] || row.child_id).join('、'))));
        });
      });
    });
    autoCard.append(createElement(document, 'div', { class: 'row' },
      createElement(document, 'b', null, '自动轮值：'), '开始日期', startInput, '天数', daysInput, '周期', cycleInput,
      createElement(document, 'button', { class: 'btn', onclick: () => {
        scopedRequest('/api/roster/auto', { method: 'POST', body: { start_date: startInput.value, days: +daysInput.value, cycle: cycleInput.value } }, reload);
      } }, '生成排班')));
    manualCard.append(createElement(document, 'div', { class: 'row' }, '手动指定：日期', dateInput, '周期', manualCycleInput,
      createElement(document, 'button', { class: 'btn green', onclick: () => {
        if (chosen.length !== 2) {
          alert('请选择 2 名幼儿');
          return;
        }
        scopedRequest('/api/roster', { method: 'POST', body: { cycle: manualCycleInput.value, date: dateInput.value, child_ids: chosen } }, reload);
      } }, '保存当日排班')),
    createElement(document, 'div', { class: 'muted' }, '点击幼儿卡片选择 2 名值日幼儿：'), choices);
    scopedRequest('/api/children', {}, rows => {
      rows.forEach(child => {
        const button = createElement(document, 'button', { class: 'btn gray small', onclick: () => {
          const index = chosen.indexOf(child.id);
          if (index >= 0) {
            chosen.splice(index, 1);
            button.classList.remove('on');
            button.style.background = '';
            return;
          }
          if (chosen.length >= 2) {
            alert('最多 2 名');
            return;
          }
          chosen.push(child.id);
          button.classList.add('on');
          button.style.background = '#ffb800';
        } }, child.nickname || child.name);
        choices.append(button);
      });
    });
    view.append(autoCard, manualCard, createElement(document, 'div', { class: 'card' }, table));
    reload();
  }

  function growth(context) {
    const { view, scopedRequest } = beginRoute(document, request, context, '能力成长曲线');
    const select = createElement(document, 'select');
    select.append(new Option('— 选择幼儿 —', ''));
    const wrap = createElement(document, 'div');
    const childId = context.params.get('child_id');
    select.addEventListener('change', () => {
      if (!select.value) return;
      scopedRequest('/api/analysis/growth?child_id=' + select.value, {}, data => drawGrowth(document, wrap, data));
    });
    view.append(createElement(document, 'div', { class: 'row' }, select), wrap);
    scopedRequest('/api/children', {}, rows => {
      rows.forEach(child => select.append(new Option(child.nickname || child.name, child.id)));
      if (childId) select.value = childId;
    });
    if (childId) scopedRequest('/api/analysis/growth?child_id=' + childId, {}, data => drawGrowth(document, wrap, data));
  }

  function search(context) {
    const { view, scopedRequest } = beginRoute(document, request, context, '明细检索');
    const childSelect = createElement(document, 'select');
    childSelect.append(new Option('全部幼儿', ''));
    const box = createElement(document, 'div');
    const showConversation = id => scopedRequest('/api/conversations/' + id, {}, data => {
      box.innerHTML = '';
      const card = createElement(document, 'div', { class: 'card' });
      card.append(createElement(document, 'b', null, `会话 #${id}`));
      data.messages.forEach(message => card.append(createElement(document, 'div', { class: `bubble ${message.role === 'child' ? 'c' : 'd'}` }, `${message.role === 'child' ? '幼儿：' : '日记本：'}${message.text}`)));
      if (data.feeding_logs.length) card.append(createElement(document, 'div', { class: 'muted teacher-detail-top' }, `饲养流水：${data.feeding_logs.map(log => `${log.category}·${log.content}`).join('；')}`));
      if (data.emotion) card.append(createElement(document, 'div', { class: 'muted' }, `情绪：${data.emotion.emotion}（强度 ${data.emotion.intensity}）`));
      box.append(card);
    });
    const load = () => {
      const query = childSelect.value ? `?child_id=${childSelect.value}` : '';
      scopedRequest('/api/conversations' + query, {}, rows => {
        box.innerHTML = '';
        if (!rows.length) {
          box.append(createElement(document, 'div', { class: 'card muted' }, '暂无记录'));
          return;
        }
        const table = createElement(document, 'table');
        table.append(createElement(document, 'tr', null,
          tableHeading(document, '会话'), tableHeading(document, '日期'), tableHeading(document, '结束原因'), tableHeading(document, '操作')));
        rows.forEach(conversation => table.append(createElement(document, 'tr', null,
          tableCell(document, conversation.id), tableCell(document, conversation.date), tableCell(document, conversation.end_reason || '-'),
          tableCell(document, createElement(document, 'button', { class: 'btn small', onclick: () => showConversation(conversation.id) }, '查看')))));
        box.append(createElement(document, 'div', { class: 'card' }, table));
      });
    };
    childSelect.addEventListener('change', load);
    view.append(createElement(document, 'div', { class: 'row' }, childSelect), box);
    scopedRequest('/api/children', {}, rows => rows.forEach(child => childSelect.append(new Option(child.nickname || child.name, child.id))));
    load();
  }

  return { children, ducks, roster, growth, search };
}
