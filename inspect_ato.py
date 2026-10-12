from pathlib import Path
import pdfplumber

ato_folder = Path("data/ato")

for pdf_file in sorted(ato_folder.glob("*.pdf")):
    with pdfplumber.open(pdf_file) as pdf:
        print(f"\nFile: {pdf_file.name}")
        print(f"Pages: {len(pdf.pages)}")

        first_page = pdf.pages[0]
        text = first_page.extract_text()

        print("First 500 characters:")
        print(text[:500] if text else "No text extracted")