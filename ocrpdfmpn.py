import re
import pandas as pd
import requests
import io
import streamlit as st
from concurrent.futures import ThreadPoolExecutor
import difflib as dlb
import fitz
import easyocr  # Import EasyOCR

def clean_string(s):
    """Remove illegal characters from a string."""
    return re.sub(r'[\x00-\x1F\x7F]', '', s) if isinstance(s, str) else s

def get_pdf_text(pdf_url):
    """Fetch and extract text from a PDF URL."""
    try:
        response = requests.get(pdf_url, timeout=10)
        response.raise_for_status()
        with fitz.open(stream=io.BytesIO(response.content), filetype='pdf') as doc:
            return '\n'.join(page.get_text() for page in doc)
    except Exception as e:
        print(f"Error processing PDF {pdf_url}: {e}")
        return None  # Explicitly return None on error

def ocr_text_from_pdf(pdf_bytes):
    """Extract text from PDF using OCR."""
    reader = easyocr.Reader(['en'])
    images = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = ''
    for page in images:
        img = page.get_pixmap()
        img_np = img.samples.reshape(img.height, img.width, img.n)
        results = reader.readtext(img_np)
        full_text += ' '.join([result[1] for result in results]) + '\n'
    return full_text.strip()

def validate_parts(pdf_data, part_col, pdf_col, data):
    """Validate parts against extracted PDF data."""
    data['STATUS'] = None
    data['EQUIVALENT'] = None
    data['SIMILARS'] = None

    def set_desc(index):
        part = data[part_col][index]
        pdf_url = data[pdf_col][index]
        
        values = pdf_data.get(pdf_url)
        if values is None:
            # Check if we can fetch and read the PDF
            values = get_pdf_text(pdf_url)
            if values is None:
                data.at[index, 'STATUS'] = 'May be Broken'
                return

        if len(values) <= 100:  # Use OCR for short text
            pdf_bytes = requests.get(pdf_url).content
            values = ocr_text_from_pdf(pdf_bytes)

        # Check for exact match
        exact_match = re.search(re.escape(part), values, flags=re.IGNORECASE)
        if exact_match:
            data.at[index, 'STATUS'] = 'Exact'
            data.at[index, 'EQUIVALENT'] = exact_match.group(0)
            return
        
        # Check for close matches
        similar_matches = dlb.get_close_matches(part, re.split(r'\W+', values), n=1, cutoff=0.65)
        if similar_matches:
            data.at[index, 'STATUS'] = 'Includes or Missed Suffixes'
            data.at[index, 'EQUIVALENT'] = similar_matches[0]
            return

        data.at[index, 'STATUS'] = 'Not Found'
        data.at[index, 'EQUIVALENT'] = 'No equivalent found'
        data.at[index, 'SIMILARS'] = 'None'

    with ThreadPoolExecutor() as executor:
        executor.map(set_desc, data.index)

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
                pdf_data = {pdf: get_pdf_text(pdf) for pdf in pdfs}

                result_data = validate_parts(pdf_data, 'MPN', 'PDF', data)

                # Clean the output data
                for col in ['MPN', 'PDF', 'STATUS', 'EQUIVALENT', 'SIMILARS']:
                    result_data[col] = result_data[col].apply(clean_string)

                # Display validation results
                st.subheader("Validation Results")
                for index, row in result_data.iterrows():
                    st.markdown(f"{row['MPN']} - {row['STATUS']} - {row['EQUIVALENT']} - {row['SIMILARS']}")

                output_file = "MPN_Validation_Result.xlsx"
                result_data.to_excel(output_file, index=False)
                st.sidebar.download_button("Download Results 📥", data=open(output_file, "rb"), file_name=output_file)

            else:
                st.error("The uploaded file must contain 'MPN' and 'PDF' columns.")
        except Exception as e:
            st.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
