(() => {
    const selector = ".btn:not(.btn-link):not(.btn-close):not(.navbar-toggler):not(.nav-link)";

    function restoreButton(button) {
        if (!button.dataset.submitFeedbackHtml) return;
        button.innerHTML = button.dataset.submitFeedbackHtml;
        button.disabled = false;
        button.classList.remove("is-submitting");
        button.removeAttribute("aria-busy");
        button.style.removeProperty("min-width");
        if (button._submitFeedbackPanel) {
            button._submitFeedbackPanel.remove();
            delete button._submitFeedbackPanel;
        }
        delete button.dataset.submitFeedbackHtml;
    }

    function showSubmitFeedback(button, form) {
        if (!button || !button.matches(selector) || button.dataset.noSubmitFeedback !== undefined) return;
        const width = button.getBoundingClientRect().width;
        button.dataset.submitFeedbackHtml = button.innerHTML;
        button.style.minWidth = `${Math.ceil(width)}px`;
        button.classList.add("is-submitting");
        button.setAttribute("aria-busy", "true");
        button.innerHTML = '<span>Processing…</span><span class="spinner-border spinner-border-sm submit-feedback-spinner" aria-hidden="true"></span>';
        button.disabled = true;

        const panel = document.createElement("div");
        panel.className = "submit-status-panel";
        panel.setAttribute("role", "status");
        panel.setAttribute("aria-live", "polite");
        panel.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><div><div class="submit-status-panel-title">Processing your request…</div><div class="submit-status-panel-detail">Please keep this page open while the action completes.</div></div>';
        form.append(panel);
        button._submitFeedbackPanel = panel;

        // Download responses can leave the current page in place.
        window.setTimeout(() => restoreButton(button), 15000);
    }

    document.addEventListener("submit", event => {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.dataset.noSubmitFeedback !== undefined) return;
        const button = event.submitter || form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
        // Defer until the browser has captured the submitter's name and value.
        window.setTimeout(() => showSubmitFeedback(button, form), 0);
    });

    window.addEventListener("pageshow", () => {
        document.querySelectorAll(".btn.is-submitting").forEach(restoreButton);
    });
})();
