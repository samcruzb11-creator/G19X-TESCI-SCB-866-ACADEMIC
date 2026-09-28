'use strict';

const menuButton = document.querySelector('.menu-toggle');
if (menuButton) {
    const closeMenu = () => {
        document.body.classList.remove('navigation-open');
        menuButton.setAttribute('aria-expanded', 'false');
    };
    menuButton.addEventListener('click', () => {
        const open = document.body.classList.toggle('navigation-open');
        menuButton.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeMenu();
    });
    document.addEventListener('click', (event) => {
        if (!event.target.closest('.sidebar, .menu-toggle')) closeMenu();
    });
    window.matchMedia('(min-width: 761px)').addEventListener('change', closeMenu);
}
