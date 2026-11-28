(() => {
  const picker = document.querySelector('.ws-picker');
  const choices = [...picker.querySelectorAll('input[type=checkbox]')];
  const printButton = picker.querySelector('.ws-print');
  const selectAll = picker.querySelector('.ws-select-all');
  const clear = picker.querySelector('.ws-clear');
  const status = picker.querySelector('[role=status]');
  const blocks = document.querySelectorAll('.ws-block');

  function update() {
    const selected = new Set(choices.filter(choice => choice.checked).map(choice => choice.value));
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
})();
