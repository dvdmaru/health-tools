(() => {
  const picker = document.querySelector('.ws-picker');
  const sampling = document.getElementById('glucose-sampling');
  const samplingChoice = picker.querySelector('input[value="glucose-sampling"]');
  const choices = [...picker.querySelectorAll('input[type=checkbox]:enabled')];
  const printButton = picker.querySelector('.ws-print');
  const selectAll = picker.querySelector('.ws-select-all');
  const clear = picker.querySelector('.ws-clear');
  const status = picker.querySelector('[role=status]');
  const blocks = document.querySelectorAll('.ws-block');

  function update() {
    const selected = new Set(choices.filter(choice => choice.checked).map(choice => choice.value));
    sampling.classList.toggle('ws-print-omit', !samplingChoice.checked);
    for (const block of blocks) {
      let count = 0;
      const references = new Set();
      for (const item of block.querySelectorAll('.ws-indicator')) {
        const include = selected.has(item.id);
        item.classList.toggle('ws-print-omit', !include);
        if (!include) continue;
        count++;
        for (const link of item.querySelectorAll('.ws-pop a, .ws-src a')) {
          references.add(link.hash.slice(1));
        }
      }
      block.classList.toggle('ws-print-omit', count === 0);
      for (const list of block.querySelectorAll('.ws-sources, .ws-population-refs')) {
        let used = false;
        for (const entry of list.querySelectorAll('li')) {
          const include = references.has(entry.id);
          entry.classList.toggle('ws-print-omit', !include);
          if (include) used = true;
        }
        list.classList.toggle('ws-print-omit', !used);
      }
    }
    status.textContent = selected.size ? '已勾選 ' + selected.size + ' 項' : '尚未勾選項目';
    printButton.disabled = clear.disabled = selected.size === 0;
    selectAll.disabled = selected.size === choices.length;
    document.querySelector('.ws-print-empty').hidden = selected.size !== 0;
  }

  function includeReportQuestion() {
    const match = /^#(first-report-[a-z-]+)(?:\/([a-f0-9-]{36}))?$/.exec(location.hash);
    if (!match) return;
    const [, anchorId, token] = match;
    const anchor = document.getElementById(anchorId);
    if (!anchor?.matches('.guide-anchor')) return;
    const item = anchor.closest('.ws-indicator');
    const choice = choices.find(input => input.value === item.id);
    if (!choice) return;
    for (const input of choices) input.checked = input === choice;
    const box = item.querySelector('.ws-question');
    let editor = box.querySelector('textarea');
    if (editor && editor.dataset.handoff === location.hash) {
      update();
      return;
    }
    if (!editor) {
      editor = document.createElement('textarea');
      editor.className = 'ws-noprint';
      editor.setAttribute('aria-label', item.querySelector('h3').textContent + '回診問題');
      editor.rows = 3;
      editor.maxLength = 500;
      const paper = document.createElement('div');
      paper.className = 'ws-carried-question';
      editor.addEventListener('input', () => { paper.textContent = editor.value; });
      const pickerLink = document.createElement('a');
      pickerLink.href = '#worksheet-choices';
      pickerLink.className = 'ws-noprint';
      pickerLink.textContent = '查看勾選項目與列印';
      pickerLink.addEventListener('click', event => {
        event.preventDefault();
        picker.scrollIntoView();
        choice.focus({preventScroll:true});
      });
      box.append(editor, paper, pickerLink);
    }
    let text = anchor.dataset.question;
    if (token) {
      text = '';
      try {
        text = sessionStorage.getItem(anchorId + '/' + token) || '';
      } catch { /* 工作表仍可直接填寫。 */ }
    }
    editor.dataset.handoff = location.hash;
    editor.value = text;
    editor.placeholder = '在這裡填寫回診問題';
    box.querySelector('.ws-carried-question').textContent = text;
    update();
    item.scrollIntoView();
    const heading = item.querySelector('h3');
    heading.tabIndex = -1;
    heading.focus({preventScroll:true});
  }

  function includeLinkedQuestion() {
    if (location.hash !== '#' + sampling.id || !samplingChoice.disabled) return;
    samplingChoice.disabled = false;
    samplingChoice.checked = true;
    samplingChoice.parentElement.hidden = false;
    sampling.classList.add('ws-added');
    choices.push(samplingChoice);
    update();
  }

  window.addEventListener('hashchange', includeReportQuestion);
  includeLinkedQuestion();
  window.addEventListener('hashchange', includeLinkedQuestion);
  picker.addEventListener('change', update);
  for (const button of [selectAll, clear]) {
    button.addEventListener('click', () => {
      for (const choice of choices) choice.checked = button === selectAll;
      update();
    });
  }
  printButton.addEventListener('click', () => window.print());
  window.addEventListener('beforeprint', update);
  window.addEventListener('pageshow', update);
  update();
  document.querySelector('main').classList.add('ws-selective');
  picker.hidden = false;
  includeReportQuestion();
})();
