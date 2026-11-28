for (const row of document.querySelectorAll('.reading-row')) {
  for (const link of row.querySelectorAll('.reading-cells a')) {
    const explanation = document.getElementById(link.hash.slice(1));
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-controls', explanation.id);
    button.setAttribute('aria-expanded', 'false');
    button.append(...link.childNodes);
    link.replaceWith(button);
    explanation.hidden = true;
  }
  row.addEventListener('click', event => {
    const clicked = event.target.closest('button[aria-controls]');
    if (!clicked) return;
    const open = clicked.getAttribute('aria-expanded') === 'false';
    for (const button of row.querySelectorAll('button[aria-controls]')) {
      const selected = button === clicked && open;
      button.setAttribute('aria-expanded', String(selected));
      document.getElementById(button.getAttribute('aria-controls')).hidden = !selected;
    }
  });
}

function revealLinkedField() {
  const target = document.getElementById(location.hash.slice(1));
  if (!target) return;
  if (target.matches('.report-sheet details')) target.open = true;
  if (target.matches('.reading-note[hidden]')) {
    const row = target.closest('.reading-row');
    row.querySelector('button[aria-controls="' + target.id + '"]').click();
    row.scrollIntoView();
  }
}
revealLinkedField();
window.addEventListener('hashchange', revealLinkedField);

const handoff = document.getElementById('alt-handoff');
const question = handoff.querySelector('textarea');
const worksheetLink = handoff.querySelector('a');
const status = handoff.querySelector('[role=status]');
handoff.querySelector('.alt-editor').hidden = false;
worksheetLink.hidden = true;
question.addEventListener('input', () => question.setCustomValidity(''));
handoff.querySelector('button').addEventListener('click', () => {
  const text = question.value.trim();
  if (!text) {
    question.setCustomValidity('請先寫下想問的問題。');
    question.reportValidity();
    return;
  }
  const destination = new URL(worksheetLink.href);
  if (text !== question.defaultValue) {
    try {
      const id = crypto.randomUUID();
      sessionStorage.setItem('first-report-alt/' + id, text);
      destination.hash += '/' + id;
    } catch {
      status.textContent = '瀏覽器無法暫存問題。請先複製上方文字，再開啟工作表，將問題貼到 GPT 提問格。';
      worksheetLink.hidden = false;
      return;
    }
  }
  location.assign(destination.href);
});
