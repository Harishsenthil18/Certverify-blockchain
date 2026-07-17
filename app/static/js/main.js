// main.js -- small progressive-enhancement helpers, no framework needed.
document.addEventListener("DOMContentLoaded", function () {

    // Auto-dismiss flash messages after 6 seconds.
    document.querySelectorAll(".flash-container .alert").forEach(function (alertEl) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alertEl);
            bsAlert.close();
        }, 6000);
    });

    // Show a loading spinner + disable the submit button on form submit,
    // to give feedback during file uploads / verification (which can take
    // a moment while the server hashes a file and checks the blockchain).
    document.querySelectorAll("form[data-loading-form]").forEach(function (form) {
        form.addEventListener("submit", function () {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                submitBtn.disabled = true;
                const originalHtml = submitBtn.innerHTML;
                submitBtn.setAttribute("data-original-html", originalHtml);
                submitBtn.innerHTML =
                    '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Processing...';
            }
        });
    });

    // Show the selected filename in custom file inputs with a dropzone look.
    document.querySelectorAll('input[type="file"][data-filename-target]').forEach(function (input) {
        input.addEventListener("change", function () {
            const targetId = input.getAttribute("data-filename-target");
            const targetEl = document.getElementById(targetId);
            if (targetEl) {
                targetEl.textContent = input.files.length
                    ? input.files[0].name
                    : "No file selected";
            }
        });
    });
});
