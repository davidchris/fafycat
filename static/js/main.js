// Main JavaScript for FafyCat

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    console.log('FafyCat FastHTML app initialized');
    
    // Add any global event listeners or initialization code here
    initializeFormHandlers();
    initializeNavigation();
    initializeHTMX();
    
    // Page-specific initialization
    if (window.location.pathname === '/review') {
        initializeReviewPage();
    }
});

// Form handling
function initializeFormHandlers() {
    // Add loading states to forms when submitted
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.textContent = 'Processing...';
                submitBtn.disabled = true;
                submitBtn.classList.add('opacity-50');
            }
        });
    });
}

// Navigation handling
function initializeNavigation() {
    // Highlight active navigation item
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('nav a');
    
    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active', 'bg-blue-500', 'text-white');
        }
    });
}

// HTMX initialization and event handlers
function initializeHTMX() {
    // Only initialize if HTMX is available
    if (typeof htmx === 'undefined') {
        console.log('HTMX not loaded, skipping HTMX initialization');
        return;
    }
    
    console.log('Initializing HTMX event handlers');
    
    // Configure HTMX
    htmx.config.globalViewTransitions = true;
    htmx.config.responseHandling = [
        {code:".*", swap: true},
        {code:"4[0-9][0-9]", error: true},
        {code:"5[0-9][0-9]", error: true}
    ];
    
    // Success feedback
    document.addEventListener('htmx:afterSwap', function(event) {
        if (event.detail.xhr.status === 200) {
            showNotification('Updated successfully', 'success');
        }
    });
    
    // Error handling
    document.addEventListener('htmx:responseError', function(event) {
        const message = event.detail.xhr.statusText || 'Request failed';
        showNotification('Error: ' + message, 'error');
    });
    
    // Loading states
    document.addEventListener('htmx:beforeRequest', function(event) {
        event.target.classList.add('htmx-loading');
    });
    
    document.addEventListener('htmx:afterRequest', function(event) {
        event.target.classList.remove('htmx-loading');
    });
    
    // Network error handling
    document.addEventListener('htmx:sendError', function(event) {
        showNotification('Network error - please check your connection', 'error');
    });
}

// Review page specific functionality
function initializeReviewPage() {
    // Update confidence threshold display
    const thresholdSlider = document.querySelector('input[name="confidence_threshold"]');
    const thresholdDisplay = document.getElementById('threshold-display');
    
    if (thresholdSlider && thresholdDisplay) {
        thresholdSlider.addEventListener('input', function() {
            const value = Math.round(parseFloat(this.value) * 100);
            thresholdDisplay.textContent = `Show transactions with confidence below ${value}%`;
        });
    }
}

// Utility functions
function showNotification(message, type = 'info') {
    // Simple notification system (can be enhanced later)
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 p-4 rounded shadow-lg z-50 ${
        type === 'error' ? 'bg-red-500 text-white' : 
        type === 'success' ? 'bg-green-500 text-white' : 
        'bg-blue-500 text-white'
    }`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 5000);
}