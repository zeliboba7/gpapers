#    gPapers
#    Copyright (C) 2007-2009 Derek Anderson
#                  2012      Derek Anderson and Marcel Stimberg
#
# This file is part of gPapers.
#
#    gPapers is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    gPapers is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with gPapers.  If not, see <http://www.gnu.org/licenses/>.

from io import BytesIO
import cStringIO
import re

from pdfminer.pdfparser import PDFParser, PDFDocument, resolve1
from pdfminer.pdfinterp import PDFResourceManager, process_pdf
from pdfminer.layout import LAParams
from pdfminer.converter import TextConverter

from gpapers.logger import log_debug

# A DOI consists of a numeric prefix starting with "10." followed by "/" and
# a more or less arbitrary suffix
p_doi = re.compile('[\s:](10.[0-9]+/[^/].+)\s', re.IGNORECASE)


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
            # Some PDFs have the doi as a title
            if title.lower().startswith('doi:'):
                paper_info['doi'] = title[4:]
            else:
                paper_info['title'] = title

        #TODO: Additional metadata?
        #TODO: What about embedded BibTeX (as done by JabRef)?

    #Extract text
    rsrcmgr = PDFResourceManager()
    content = cStringIO.StringIO()
    device = TextConverter(rsrcmgr, content, codec='utf-8', laparams=LAParams())
    process_pdf(rsrcmgr, device, fp, check_extractable=True, caching=True)

    paper_info['extracted_text'] = content.getvalue()

    if not 'doi' in paper_info:  # Try to find a DOI in the text
        doi = p_doi.search(paper_info['extracted_text'])
        if doi is not None:
            doi = doi.group(1)
            log_debug('Found a DOI: %s' % doi)
            paper_info['doi'] = doi

    device.close()
    content.close()

    log_debug('Exctracted paper_info from PDF: %s' % paper_info)

    return paper_info
