import pdfplumber

file = "data/ato/fortnightly_2026.pdf"

with pdfplumber.open(file) as pdf:
    page = pdf.pages[0]

    text = page.extract_text(layout=False)

    for line in text.splitlines()[:25]:
        print(line)