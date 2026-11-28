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
  const practice = target?.closest('.report-practice');
  for (const section of document.querySelectorAll('.report-practice')) {
    section.hidden = target?.id === 'first-report' || (practice != null && section !== practice);
  }
  if (!target) return;
  if (target.matches('.report-sheet details')) target.open = true;
  if (target.matches('.reading-note')) {
    const row = target.closest('.reading-row');
    const button = row.querySelector('button[aria-controls="' + target.id + '"]');
    if (target.hidden) button.click();
    button.focus({preventScroll:true});
    row.scrollIntoView();
  } else if (target.matches('.reading-row')) {
    target.scrollIntoView();
  } else if (target === practice) {
    practice.scrollIntoView();
    practice.querySelector('h3').focus({preventScroll:true});
  }
}
revealLinkedField();
window.addEventListener('hashchange', revealLinkedField);

// 已在同一個錨點時再選一次，瀏覽器不會觸發 hashchange。
for (const link of document.querySelectorAll('.guide-options a[href^="#"]')) {
  link.addEventListener('click', () => {
    if (link.hash === location.hash) revealLinkedField();
  });
}

for (const handoff of document.querySelectorAll('.report-handoff')) {
  const question = handoff.querySelector('textarea');
  const worksheetLink = handoff.querySelector('.worksheet-link');
  const status = handoff.querySelector('[role=status]');
  handoff.querySelector('.question-editor').hidden = false;
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
        sessionStorage.setItem(destination.hash.slice(1) + '/' + id, text);
        destination.hash += '/' + id;
      } catch {
        status.textContent = '瀏覽器無法暫存問題。請先複製上方文字，再開啟工作表，將問題貼到該項提問格。';
        worksheetLink.hidden = false;
        return;
      }
    }
    location.assign(destination.href);
  });
}

const advice = document.getElementById('followup-form');
const adviceQuestion = advice.querySelector('#advice-question');
const adviceOriginal = advice.querySelector('#advice-original');
const adviceChecks = [...advice.querySelectorAll('fieldset')];
const regenerate = advice.querySelector('#advice-regenerate');
let suggested = '';

function updateAdviceQuestion() {
  const choices = adviceChecks.map(group => group.querySelector(':checked'));
  const ready = choices.every(Boolean);
  advice.querySelector('#advice-editor').hidden = !ready;
  if (!ready) return;
  const keepEdits = adviceQuestion.value !== suggested;
  suggested = adviceChecks.filter((_, index) => choices[index].value === 'missing')
    .map(group => group.querySelector('legend').textContent).join(' ');
  if (!keepEdits) adviceQuestion.value = suggested;
  adviceQuestion.setCustomValidity('');
  regenerate.hidden = adviceQuestion.value === suggested || !suggested;
  advice.querySelector('#advice-note').textContent = suggested
    ? '問題依你標為「我的報告也沒寫」的欄位整理，可在下方改寫。'
    : '三項都找到了，沒有疑問就完成了這一步。如果想帶原文去回診，請先寫下想問的問題。';
}

advice.hidden = false;
for (const group of adviceChecks) group.addEventListener('change', updateAdviceQuestion);
regenerate.addEventListener('click', () => {
  adviceQuestion.value = suggested;
  adviceQuestion.setCustomValidity('');
  regenerate.hidden = true;
  adviceQuestion.focus();
});
adviceQuestion.addEventListener('input', () => {
  regenerate.hidden = !suggested || adviceQuestion.value === suggested;
});
for (const field of [adviceOriginal, adviceQuestion]) {
  field.addEventListener('input', () => field.setCustomValidity(''));
}
advice.addEventListener('submit', event => {
  event.preventDefault();
  if (!adviceChecks.every(group => group.querySelector(':checked'))) return;
  for (const field of [adviceOriginal, adviceQuestion]) {
    if (!field.value.trim()) {
      field.setCustomValidity('請填寫這一欄。');
      field.reportValidity();
      return;
    }
  }
  try {
    const key = 'followup-advice/' + crypto.randomUUID();
    sessionStorage.setItem(key, JSON.stringify({name: adviceOriginal.value, question: adviceQuestion.value}));
    location.assign('/worksheet/#' + key);
  } catch {
    advice.querySelector('.advice-error').textContent = '瀏覽器無法暫存這兩欄，請先複製原文與問題留存。';
  }
});
window.addEventListener('pageshow', updateAdviceQuestion);
