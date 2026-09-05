/* /game/<id> page: show/hide the trick list under each hand. */
function toggleTricks(handNumber) {
    const el = document.getElementById('tricks-' + handNumber);
    el.classList.toggle('show');
    const btn = el.previousElementSibling;
    if (el.classList.contains('show')) {
        btn.textContent = 'Hide Trick Details ▲';
    } else {
        btn.textContent = 'Show Trick Details ▼';
    }
}
    
