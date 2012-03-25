from io import BytesIO

from pdfminer.pdfparser import PDFParser, PDFDocument, resolve1

from logger import log_debug, log_info, log_error


def get_paper_info_from_pdf(data):
    fp = BytesIO(data)
    # Create a PDF parser object associated with the file object.
    parser = PDFParser(fp)
    # Create a PDF document object that stores the document structure.
    doc = PDFDocument()
    # Connect the parser and document objects.
    parser.set_document(doc)
    doc.set_parser(parser)
    # Initialize
    doc.initialize()
    # Extract the metadata
    for xref in doc.xrefs:
        info_ref = xref.trailer.get('Info')
        if info_ref:
            info = resolve1(info_ref)

    paper_info = {}
    if info:
        authors = info.get('Author')
        if authors:
            if ';' in authors:
                author_list = authors.split(';')
            elif ' AND ' in authors:
                author_list = authors.split(' AND ')
            elif ',' in authors:
                #FIXME: This cuts 'LastName, FirstName' in two...
                author_list = authors.split(',')
            else:
                author_list = [authors]

            paper_info['authors'] = author_list
        title = info.get('Title')
        if title:
            paper_info['title'] = title

        #TODO: Additional metadata?
        #TODO: What about embedded BibTeX (as done by JabRef)?

    #TODO: Extract text
    #TODO: Find doi

    return paper_info
