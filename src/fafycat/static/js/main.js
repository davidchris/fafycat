// Main JavaScript for FafyCat — Bauhaus Dark Mode

// Global HTML escaping utility
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
window.escapeHtml = escapeHtml;

// js-enabled class is set inline in <head> for immediate effect

document.addEventListener('DOMContentLoaded', function() {
    initializeNavigation();
    initializeSidebar();
    initializeHTMX();
    initializeFormHandlers();

    if (window.location.pathname === '/review') {
        initializeReviewPage();
    }
});

// Sidebar toggle
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    const button = document.getElementById('hamburger-btn');

    if (!sidebar || !backdrop) return;

    const isOpen = sidebar.classList.toggle('open');
    backdrop.classList.toggle('open', isOpen);

    if (button) {
        button.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }

    backdrop.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
}

function initializeSidebar() {
    const button = document.getElementById('hamburger-btn');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!button || !backdrop) return;

    button.addEventListener('click', toggleSidebar);
    backdrop.addEventListener('click', toggleSidebar);

    document.addEventListener('keydown', function(event) {
        if (event.key !== 'Escape') return;

        const sidebar = document.getElementById('sidebar');
        if (!sidebar || !sidebar.classList.contains('open')) return;

        toggleSidebar();
    });
}

// Navigation — highlight active link
function initializeNavigation() {
    const currentPath = window.location.pathname;
    document.querySelectorAll('.sidebar-link').forEach(link => {
        const linkPath = link.getAttribute('data-path') || link.getAttribute('href');
        if (linkPath === currentPath) {
            link.classList.add('active');
        }
    });
}

// Form handling
function initializeFormHandlers() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.classList.contains('no-disable')) {
                submitBtn.textContent = 'Processing...';
                submitBtn.disabled = true;
                submitBtn.style.opacity = '0.5';
            }
        });
    });
}

// HTMX initialization
function initializeHTMX() {
    if (typeof htmx === 'undefined') return;

    htmx.config.globalViewTransitions = true;
    htmx.config.responseHandling = [
        {code:"204", swap: false},
        {code:"4[0-9][0-9]", error: true},
        {code:"5[0-9][0-9]", error: true},
        {code:".*", swap: true}
    ];

    document.addEventListener('htmx:afterSwap', function(event) {
        if (event.detail.xhr.status === 200) {
            showNotification('Updated successfully', 'success');
        }
    });

    document.addEventListener('htmx:responseError', function(event) {
        const message = event.detail.xhr.statusText || 'Request failed';
        showNotification('Error: ' + message, 'error');
    });

    document.addEventListener('htmx:beforeRequest', function(event) {
        event.target.classList.add('htmx-loading');
    });

    document.addEventListener('htmx:afterRequest', function(event) {
        event.target.classList.remove('htmx-loading');
    });

    document.addEventListener('htmx:sendError', function() {
        showNotification('Network error — check your connection', 'error');
    });
}

// Review page
function initializeReviewPage() {
    const thresholdSlider = document.querySelector('input[name="confidence_threshold"]');
    const thresholdDisplay = document.getElementById('threshold-display');

    if (thresholdSlider && thresholdDisplay) {
        thresholdSlider.addEventListener('input', function() {
            const value = Math.round(parseFloat(this.value) * 100);
            thresholdDisplay.textContent = `Show transactions with confidence below ${value}%`;
        });
    }
}

// Toast notification system
function showNotification(message, type = 'info') {
    const toast = document.createElement('div');
    const typeClass = {
        error: 'toast-error',
        success: 'toast-success',
        warning: 'toast-warning',
        info: 'toast-info'
    }[type] || 'toast-info';

    toast.className = `toast ${typeClass}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.2s ease';
        setTimeout(() => toast.remove(), 200);
    }, 4000);
}
