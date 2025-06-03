// Main JavaScript for FafyCat

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    console.log('FafyCat FastHTML app initialized');
    
    // Add any global event listeners or initialization code here
    initializeFormHandlers();
    initializeNavigation();
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