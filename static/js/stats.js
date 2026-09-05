/* /stats page: collapsible sections + tap feedback on mobile cards. */
function toggleSection(sectionId) {
    const section = document.getElementById(sectionId);
    const chevronId = sectionId.replace('Section', 'Chevron');
    const chevron = document.getElementById(chevronId);

    section.classList.toggle('expanded');

    if (section.classList.contains('expanded')) {
        chevron.textContent = '▲';
    } else {
        chevron.textContent = '▼';
    }
}

// Add smooth scrolling for mobile and touch interactions
document.addEventListener('DOMContentLoaded', function () {
    // Add click handlers for cards on mobile for better interaction
    if (window.innerWidth <= 767) {
        document.querySelectorAll('.player-card').forEach(card => {
            card.addEventListener('click', function () {
                this.style.transform = 'scale(0.98)';
                setTimeout(() => {
                    this.style.transform = '';
                }, 150);
            });
        });
    }
});
    

document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action="toggleSection"]');
    if (el) toggleSection(el.dataset.arg);
});
