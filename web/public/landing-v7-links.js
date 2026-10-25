/* Navigation only. The v7 document, styles, fonts and animation are unchanged. */
(() => {
  const desk = '/desk?demo=guided';
  const sections = {overview:'overview', work:'cases', review:'approvals', report:'reports', learning:'learning'};
  document.addEventListener('click', (event) => {
    const control = event.target.closest?.('[data-view],[data-desk],[data-case-action],[data-action]');
    if (!control) return;
    let destination;
    if (control.dataset.view && control.dataset.view !== 'landing') destination = desk;
    if (control.dataset.desk) destination = `${desk}&section=${sections[control.dataset.desk] || 'cases'}`;
    if (control.dataset.caseAction) destination = desk;
    if (control.dataset.action === 'sponsors') destination = `${desk}&section=overview`;
    if (!destination) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    window.location.assign(destination);
  }, true);
})();
