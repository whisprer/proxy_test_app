// js/script.js

document.addEventListener('DOMContentLoaded', () => {
    console.log("Whispr Skin: JavaScript is active!");

    // =========================================================
    // Needless Show-off Effect: Text Scramble on Hover
    // Target any element with data-scramble-text attribute
    // Example usage in HTML: <h1 data-scramble-text>Whispr Skin</h1>
    // =========================================================

    const scrambleElements = document.querySelectorAll('[data-scramble-text]');
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()-=_+[]{}|;:',.<>/?";
    let intervals = {}; // To store intervals for each element

    scrambleElements.forEach(element => {
        let originalText = element.textContent;

        const startScramble = () => {
            let iteration = 0;
            intervals[element] = setInterval(() => {
                element.textContent = originalText.split('')
                    .map((char, index) => {
                        if (index < iteration) {
                            return originalText[index];
                        }
                        return chars[Math.floor(Math.random() * chars.length)];
                    })
                    .join('');

                if (iteration >= originalText.length) {
                    clearInterval(intervals[element]);
                }
                iteration += 1 / 3; // Controls speed of reveal
            }, 30); // Controls speed of scramble
        };

        const stopScramble = () => {
            clearInterval(intervals[element]);
            element.textContent = originalText; // Reset to original text
        };

        // Add event listeners for hover
        element.addEventListener('mouseenter', startScramble);
        element.addEventListener('mouseleave', stopScramble);

        // Optional: Trigger scramble on page load for initial effect
        // startScramble(); // Uncomment this line if you want it to scramble on load
    });

    // =========================================================
    // Simple current year update for footer (optional but good practice)
    // =========================================================
    const currentYearSpan = document.getElementById('current-year');
    if (currentYearSpan) {
        currentYearSpan.textContent = new Date().getFullYear();
    }

    // You can add more general-purpose JavaScript below here.
    // For example:
    // - Smooth scrolling for anchor links
    // - Simple mobile navigation toggle
    // - Form validation (more complex, often needs server-side)
});
