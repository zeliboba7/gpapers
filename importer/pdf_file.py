import os

from gi.repository import Soup  # @UnresolvedImport
from gi.repository import Gio  # @UnresolvedImport

from pdfminer.pdfparser import PDFParser, PDFDocument, resolve1

from logger import log_debug, log_info, log_error
from importer import RessourceProvider


class PdfFileRessourceProvider(RessourceProvider):

    def provides_infos_for_file(self, filename, content_type):
        return content_type == 'application/pdf'

    def get_infos_for_file(self, filename, callback, error_callback):
        # TODO: Use async GIO methods?
        fp = open(filename, 'rb')
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

        callback(paper_info)

    def get_document_for_file(self, filename, callback, error_callback):
        #TODO: Copy the file to our PDF directory
        return filename

if __name__ == '__main__':
    import sys
    pdf_ressource = PdfFileRessourceProvider()
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if pdf_ressource.provides_infos_for_file(arg):
                print 'Infos for %s' % arg

                def print_all(paper_info):
                    for key, value in paper_info.items():
                        print key, ':', value

                paper_info = pdf_ressource.get_infos_for_file(arg,
                                                              print_all,
                                                              None)







