# Green Orbit — End-User Guide

Last updated: 31 October 2026

Review and update this guide with every production release. The in-application Help page is the concise operational version of this guide.

## Getting started

Sign in using your Green Orbit account. The administrator menu groups features into **People**, **Time & Billing**, **Payroll**, and **Automation**. Select a group to expand it. The current section opens automatically, and other expanded groups are remembered. On smaller screens, use the menu button to open the same navigation.

## People

### Organisations

Organisations represent employing businesses and customers. Create or edit an organisation with its name and valid 11-digit ABN. Configure its ABA profile before producing bank payment files.

### Workers

Workers contain identity, contact, tax, payment, superannuation, leave, document, and portal-access records. Open a worker to manage these areas. Deactivate a worker when appropriate instead of removing payroll history.

### Assignments and work patterns

An assignment links a worker to a customer and defines billing arrangements. A work pattern records the worker's employment and pay terms, pay basis, ordinary hours, pay frequency, rates, and effective dates. Confirm that both records cover the intended time, invoice, and payroll periods.

## Time & Billing

### Timesheets

Green Orbit supports daily and weekly timesheets. Select the correct assignment and pay component, enter hours for the correct dates, and review the entries before approval. Approved time can feed invoicing and payroll, subject to validation.

### Timesheet Runs

Timesheet Runs generate and manage scheduled timesheets for a period. Filter by customer, worker, or status. Review generated entries before saving and approving them.

### Invoices

Invoices are created from eligible approved time using the assignment's customer and billing rates. Confirm the source records, customer, rates, totals, and status before progressing an invoice. Invoice lists and previews provide access to generated PDFs.

## Payroll

### Payroll readiness

Run readiness checks before processing payroll. Resolve critical findings using their worker or timesheet links. Review warnings and record the decision to proceed under your organisation's payroll controls.

### Pay Runs

Create a Pay Run for the correct organisation, pay period, and payment date. Process it, review every worker calculation, then approve and complete the run in sequence. A draft or unapproved run is not completed payroll.

### Payslips

Payslips show earnings, deductions, superannuation, and net pay resulting from payroll. Verify the worker, period, and amounts before distribution. Preview and PDF actions are available from the Payslips and Pay Run screens.

### PBT Schedules

PBT (Pay, Bill & Time) Schedules define customer cycles and generate scheduled periods. Check the customer, effective dates, frequency, generated-through date, and active status.

### Pay Components

Pay Components classify time and payroll amounts, such as ordinary hours or allowances. Configure definitions centrally and assign the allowed components to each assignment. Because component configuration can affect calculations, verify it before approving source time or payroll.

## Worker documents and secure forms

Open **Workers → Documents** to upload PDFs, preview files, and track processing. Supported documents move through statuses such as Uploaded, Ready for review, Approved, Rejected, or Failed.

When a document is ready for review, compare extracted values with the original PDF. Correct reviewable fields where necessary, then approve or reject it. Approval can update the worker's payroll profile. Review decisions must remain human-controlled.

Workers may submit secure TFN and superannuation forms through the portal. Review these submissions before applying them. Never ask a worker to provide a TFN, bank account number, password, or document image through AI chat, ordinary messages, or a Help enquiry.

## Notifications

Notifications report document, secure-form, compliance, and other workflow activity. Open a notification to follow its action link. Use the unread and all filters, and mark notifications as read after review.

## Payments and ABA files

Configure the organisation's ABA profile, then prepare a payment batch from an eligible Pay Run. Review every recipient, bank destination, lodgement reference, and amount. Manual direct-entry lines are not payroll and require a reason.

Validate and download the ABA file only after review. Export locks the batch and records a SHA-256 checksum. Follow your organisation's segregation-of-duties and bank-upload verification process; Green Orbit does not replace bank authorisation.

## Worker portal

Enable portal access from the worker's record. Portal users can:

- view payslips;
- create and review timesheets;
- see leave balances and request leave;
- review assignments;
- upload and replace eligible PDF documents;
- complete secure payroll-setup forms;
- read notifications;
- update permitted profile information; and
- contact payroll without sending sensitive values.

The portal dashboard shows incomplete payroll setup. A missing item provides a secure action; a pending item is under review. Bank, tax, and superannuation changes remain subject to payroll verification.

## Automation

### Payroll Agent

The Payroll Agent is a supervised workflow for a scheduled assignment period. It creates a draft timesheet from the effective work pattern and pauses for human review of generated hours. After confirmation it checks assignment, pay and bill rates, TFN declaration, super choice, and bank details.

If information is missing, the run remains at **Waiting for requirements** with a link for each blocker. Resolve the underlying record and select Retry when required. Once ready, the agent approves the reviewed timesheet, creates draft invoice and payroll records, reconciles their source records, and presents a handoff for human approval.

The Payroll Agent never issues an invoice, finalises payroll, or releases payment. Its run page records steps, decisions, safe diagnostics, and links to generated records without including sensitive TFN or bank values.

### AI Assistant

The AI Assistant is available from the full Assistant page and the floating **Ask Green Orbit** button. It answers questions through allowlisted read-only tools and can summarise selected timesheet, assignment, payroll, invoicing, and worker information. Answers based on application data include links to source records.

The assistant cannot run arbitrary database queries, reveal sensitive tax or bank details, send notifications, approve records, or perform payroll actions. Treat source records—not generated prose—as authoritative.

Worker portal tools are restricted to the authenticated worker's own timesheets, payslips, leave, assignments, documents, and notifications. Worker identity comes from the session and cannot be selected by the model or browser.

### Agent Monitor

Agent Monitor displays runtime status and diagnostic information for automation tasks. Use it to investigate failures and handoffs. The linked worker, timesheet, invoice, and Pay Run records remain the authoritative business records.

## Troubleshooting

- **Assignment unavailable:** confirm that the worker is linked to the correct customer and that assignment dates cover the relevant period.
- **Payroll or invoice blocked:** check source approval, effective dates, rates, worker setup, and Payroll Readiness findings.
- **Document failed:** confirm it is a supported, readable PDF and upload a clean replacement. Check Notifications for processing details.
- **Worker cannot sign in:** review portal access and account status from the worker record.
- **Action rejected:** read the displayed error, correct the identified record, and retry only when safe.
- **Issue persists:** contact the system administrator with the record identifier and error message, excluding sensitive values.

## Local AI configuration (administrators)

The AI Assistant requires `GEMINI_API_KEY` and `GEMINI_MODEL` in the backend environment. Keep API keys in the ignored `.env` file for local development or Secret Manager in Cloud Run. Never place them in templates, browser JavaScript, screenshots, or documentation examples containing real values. Restart the web service after changing runtime environment variables.
