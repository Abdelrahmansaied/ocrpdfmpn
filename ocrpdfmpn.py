import re
import pandas as pd
import requests
import io
import streamlit as st
from concurrent.futures import ThreadPoolExecutor
import difflib as dlb
import fitz
import traceback
import easyocr  # Import EasyOCR
import numpy as np

def clean_string(s):
    """Remove illegal characters from a string."""
    if isinstance(s, str):
        return re.sub(r'[\x00-\x1F\x7F]', '', s)
    return s

def GetPDFResponse(pdf):
    """Get PDF response from URL and return content."""
    try:
        response = requests.get(pdf, timeout=10)
        response.raise_for_status()
        return pdf, io.BytesIO(response.content)
    except Exception as e:
        print(f"Error fetching PDF {pdf}: {e}")
        return pdf, None

def GetPDFText(pdfs):
    """Extract text from a list of PDF URLs."""
    pdfData = {}
    chunks = [pdfs[i:i + 100] for i in range(0, len(pdfs), 100)]

    for chunk in chunks:
        with ThreadPoolExecutor() as executor:
            results = list(executor.map(GetPDFResponse, chunk))

        for pdf, byt in results:
            if byt is not None:
                try:
                    with fitz.open(stream=byt, filetype='pdf') as doc:
                        pdfData[pdf] = '\n'.join(page.get_text() for page in doc)
                except Exception as e:
                    print(f"Error reading PDF {pdf}: {e}")

    return pdfData

def ocr_text_from_pdf(pdf_bytes):
    """Extract text from PDF using OCR."""
    reader = easyocr.Reader(['en'])  # Initialize OCR reader
    try:
        images = fitz.open(stream=pdf_bytes, filetype="pdf")
        full_text = ''
        for page in images:
            img = page.get_pixmap()  # Get image from page
            img_np = np.frombuffer(img.samples, dtype=np.uint8).reshape(img.height, img.width, img.n)
            results = reader.readtext(img_np)
            full_text += ' '.join([result[1] for result in results]) + '\n'
        return full_text.strip()
    except Exception as e:
        print(f"Error with OCR processing: {e}")
        return ""

def PN_Validation_New(pdf_data, part_col, pdf_col, data):
    """Validate parts against extracted PDF data."""
    data['STATUS'] = None
    data['EQUIVALENT'] = None
    data['SIMILARS'] = None

    def SET_DESC(index):
        part = data[part_col][index]
        pdf_url = data[pdf_col][index]
        
        if pdf_url not in pdf_data:
            data['STATUS'][index] = 'May be Broken'
            return

        values = pdf_data[pdf_url]
        if len(values) <= 100:  # Use OCR when text is too short
            pdf_bytes = requests.get(pdf_url).content
            extracted_text = ocr_text_from_pdf(pdf_bytes)
            values = extracted_text  # Update values to the OCR extracted text

        # Now perform the same checks as done for regular PDF text
        exact = re.search(re.escape(part), values, flags=re.IGNORECASE)
        if exact:
            data['STATUS'][index] = 'Exact'
            data['EQUIVALENT'][index] = exact.group(0)
            semi_regex = {
                match.strip() for match in re.findall(r'\b\w*' + re.escape(part) + r'\w*\b', values, flags=re.IGNORECASE)
            }
            if semi_regex:
                data['SIMILARS'][index] = '|'.join(semi_regex)
            return

        dlb_match = dlb.get_close_matches(part, re.split('[ \n]', values), n=1, cutoff=0.65)
        if dlb_match:
            pdf_part = dlb_match[0]
            data['STATUS'][index] = 'Includes or Missed Suffixes'
            data['EQUIVALENT'][index] = pdf_part
            return

        data['STATUS'][index] = 'Not Found'

    with ThreadPoolExecutor() as executor:
        executor.map(SET_DESC, data.index)

    return data

def main():
    st.title("MPN PDF Validation App 📝")

    uploaded_file = st.file_uploader("Upload Excel file with MPN and PDF URL", type=["xlsx"])
    if uploaded_file is not None:
        try:
            data = pd.read_excel(uploaded_file)
            st.write("### Uploaded Data:")
            st.dataframe(data)

            if all(col in data.columns for col in ['MPN', 'PDF']):
                pdfs = data['PDF'].tolist()
                pdf_data = GetPDFText(pdfs)
                result_data = PN_Validation_New(pdf_data, 'MPN', 'PDF', data)

                # Clean the output data
                for col in ['MPN', 'PDF', 'STATUS', 'EQUIVALENT', 'SIMILARS']:
                    result_data[col] = result_data[col].apply(clean_string)

                # Display validation results
                st.subheader("Validation Results")
                STATUS_color = {
                    'Exact': 'green',
                    'Includes or Missed Suffixes': 'orange',
                    'Not Found': 'red',
                    'May be Broken': 'gray'
                }

                for index, row in result_data.iterrows():
                    color = STATUS_color.get(row['STATUS'], 'black')
                    st.markdown(f"<div style='color: {color};'>{row['MPN']} - {row['STATUS']} - {row['EQUIVALENT']} - {row['SIMILARS']}</div>", unsafe_allow_html=True)

                output_file = "MPN_Validation_Result.xlsx"
                result_data.to_excel(output_file, index=False, engine='openpyxl')
                st.sidebar.download_button("Download Results 📥", data=open(output_file, "rb"), file_name=output_file)

            else:
                st.error("The uploaded file must contain 'MPN' and 'PDF' columns.")
        except Exception as e:
            st.error(f"An error occurred while processing: {e}")
            st.error(traceback.format_exc())

if __name__ == "__main__":
    main()
