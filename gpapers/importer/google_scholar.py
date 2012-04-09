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

import urllib, hashlib, random, traceback

from gi.repository import Soup  # @UnresolvedImport

import BeautifulSoup
from django.template import defaultfilters

from gpapers.logger import log_debug, log_info, log_error
from gpapers.importer.bibtex import paper_info_from_bibtex
from gpapers.importer import SimpleWebSearchProvider, html_strip, soup_session

BASE_URL = 'http://scholar.google.com/'


class GoogleScholarSearch(SimpleWebSearchProvider):

    name = 'Google Scholar'
    label = 'google_scholar'
    icon = 'favicon_google.ico'
    unique_key = 'import_url'

    def __init__(self):
        SimpleWebSearchProvider.__init__(self)

        # create a "google ID" used later for setting our preferences instead
        # of using a cookie
        self.google_id = hashlib.md5(str(random.random())).hexdigest()[:16]

    def prepare_search_message(self, search_string):

        uri_string = BASE_URL + 'scholar?' + urllib.urlencode({'q': search_string})
        message = Soup.Message.new(method='GET',
                                   uri_string=uri_string)
        log_info('Starting google scholar request with uri_string="%s"' % uri_string)
        # This tells Google Scholar to return links to BibTeX
        message.request_headers.append('Cookie',
                                       'GSP=ID=%s:CF=4' % self.google_id)
        return message

    def parse_response(self, response):
        node = BeautifulSoup.BeautifulSoup(response,
                                           convertEntities=BeautifulSoup.BeautifulSoup.HTML_ENTITIES)
        papers = []
        for result in node.findAll('div', attrs={'class': 'gs_r'}):
            paper = {}
            try:
                title_node = result.findAll('h3',
                                            attrs={'class': 'gs_rt'})[0]
                #Can be a link or plain text
                title_link = title_node.findAll('a')
                if title_link:
                    log_debug('title_link: %s' % \
                              title_link[0].prettify())
                    paper['title'] = title_link[0].string
                    paper['import_url'] = title_link[0]['href']
                else:
                    paper['title'] = title_node.string
                    paper['import_url'] = ''

                if not paper['import_url'].startswith('http'):
                    paper['import_url'] = BASE_URL + paper['import_url']

                try:
                    author_journal_publisher = result.findAll('div',
                                             attrs={'class': 'gs_a'})[0]
                    log_debug('Author string: %s' % \
                                     str(author_journal_publisher.text))
                    authors, journal, publisher = \
                              author_journal_publisher.text.split(' - ')
                    paper['authors'] = authors.split(',')
                    journal_year = journal.split(',')
                    if len(journal_year) == 2:
                        paper['journal'] = journal_year[0]
                        paper['year'] = journal_year[1]
                    elif len(journal_year) == 1:  # might be a year or a journal
                        try:
                            paper['year'] = str(int(journal_year[0]))
                        except ValueError:
                            paper['journal'] = journal_year[0]
                    paper['publisher'] = publisher
                except:
                    pass

                try:
                    paper['abstract'] = html_strip(result.findAll('div',
                                                                  attrs='gs_rs')[0].text)
                except:
                    pass

                # Also attach the html data so it can be used later for
                # importing the document
                paper['data'] = result
            except:
                traceback.print_exc()
            papers.append(paper)

        return papers

    def _got_bibtex(self, message, callback, user_data):
        if message.status_code == Soup.KnownStatusCode.OK:
            bibtex_data = message.request_body.data
            log_debug('Received BibTeX data:\n%s' % bibtex_data)
            paper_info = paper_info_from_bibtex(bibtex_data)
        else:
            log_error('google scholar got status code %d' % message.status_code)
            paper_info = None
        callback(paper_info, None, user_data)

    def import_paper_after_search(self, data, callback):
        log_info('Trying to import google scholar citation')
        try:
            citations = data.findAll('div', {'class': 'gs_fl'})[0]
            log_debug('Citations: %s' % str(citations))
            for link in citations.findAll('a'):
                log_debug('Link: %s' % str(link))
                if link['href'].startswith('/scholar.bib'):
                    log_debug('Found BibTex link: %s' % link['href'])

                    def bibtex_callback(session, message, user_data):
                        self._got_bibtex(message, callback, user_data)

                    message = Soup.Message.new(method='GET',
                                               uri_string=BASE_URL + link['href'])
                    message.request_headers.append('Cookie',
                                       'GSP=ID=%s:CF=4' % self.google_id)
                    soup_session.queue_message(message, bibtex_callback,
                                               self.label)
                    #FIXME: Google scholar does not always seem to include the
                    #       URL in the bibtex data -- in this case add a link
        except:
            traceback.print_exc()
