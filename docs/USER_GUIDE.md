# Green Orbit — End-User Guide

Last updated: 15 October 2026

Review and update this guide with every production release.

## Getting Started

Sign in using your Green Orbit account. Use the navigation menu to access the main application screens. On mobile devices, open the navigation menu using the menu button.

## Organisations

Use Organisations to manage business and customer records. Select New Organisation to create a record. Enter the organisation name and its 11-digit Australian Business Number (ABN). Existing organisations can be edited from the organisation list.

## Employees

Use Employees to create and maintain employee records. Select an employee to view their details and work patterns. Employee information should be checked before processing payroll.

## Agreements (Work Patterns)

Work Patterns define an employee's employment type, pay basis, hourly rate, ordinary weekly hours, pay frequency and effective dates. Create agreements from the employee's details page. Review the agreement before processing payroll.

## Work Engagements (Assignment)

Work Engagements connect an employee to a customer organisation and define the hourly billing rate. Create or edit assignments from the Work Engagements screen. An appropriate assignment is required when generating an invoice from a timesheet.

## Timesheets

Use Timesheets to record hours worked. Green Orbit supports daily and weekly timesheets. Review hours and dates before approving a timesheet. Approved timesheets can be used for payroll and invoicing, subject to system validation.

## Pay Runs

Use Pay Runs to prepare employee payroll. Create a pay run, process it, review the results and approve it before completion. Check employee agreements, approved timesheets and calculated amounts carefully. Do not treat a draft or unapproved pay run as a completed payroll.

## Payslips

Use Payslips to view payroll results and access available payslip PDFs. Verify the pay period, employee, earnings and deductions before distributing a payslip.

## Invoices

Invoices are generated from approved timesheets using the selected Work Engagement and its customer billing rate. Open Timesheets, select Generate Invoice for an eligible approved timesheet and choose the relevant engagement. The Invoices screen lists generated invoices and provides available invoice actions and PDF access.

## Troubleshooting

If a Assignment does not appear during invoice generation, confirm that an engagement exists for the timesheet employee. If an action is rejected, read the displayed error and check required fields, approval status and record dates. Contact your system administrator if the problem persists.

## AI Assistant

Green Orbit includes a conversational AI Assistant at `/ui/ai-assistant`.
The assistant can answer general questions and retrieve selected read-only
information about outstanding timesheets, timesheet status, engagements, and
payroll summaries. It can also tell a narrative summary of a worker or
assignment across timesheets, payroll, and invoicing, with charts when those
figures benefit from a visual comparison. For example, ask “Tell me the story
of Assignment #7” or “Summarise payroll and invoicing for Jane Smith over the
last quarter.” It cannot run arbitrary database queries, reveal sensitive
tax or banking details, send notifications, or perform payroll actions.

### Gemini configuration

Create a Gemini API key in Google AI Studio and set these backend environment
variables:

```text
GEMINI_API_KEY=your-api-key
GEMINI_MODEL=gemini-3.8-flash
```

For local development, add the values to the repository's ignored `.env`
file. Restart Uvicorn after changing them. The API key is read only by the
backend and must never be placed in a template or browser JavaScript.

For Cloud Run, store the key in Google Secret Manager and expose it as
`GEMINI_API_KEY`; configure `GEMINI_MODEL` as a normal environment variable.
For example:

```bash
gcloud run services update green-orbit-payroll \
  --region=australia-southeast2 \
  --update-secrets=GEMINI_API_KEY=green-orbit-gemini-api-key:latest \
  --update-env-vars=GEMINI_MODEL=gemini-3.8-flash
```

The Cloud Run runtime service account must have Secret Manager Secret
Accessor permission for that secret. If the key is absent, the rest of the
application remains available and chat requests return a configuration error.

### Running locally

Install dependencies, configure PostgreSQL and the environment variables,
then run:

```bash
uvicorn app.main:app --reload
```

Run the focused assistant tests with:

```bash
python -m pytest -q tests/test_ai_assistant.py
```

### Synthetic demo data

The deterministic demo-data generator can create up to 200 clearly labelled
synthetic workers with mixed engagement types and the supporting records needed
for timesheets, invoicing, payroll, and AI Assistant analytics. It previews by
default and writes the entire batch in one transaction only with `--confirm`:

```bash
python -m app.demo_seed --workers 200 --seed 20261026
python -m app.demo_seed --workers 200 --seed 20261026 --confirm
```

Use a different seed for another batch. Reusing a seed is rejected to avoid
accidental duplicates. Synthetic workers use the reserved `example.invalid`
domain and synthetic payment details; never run this against a production
database.

