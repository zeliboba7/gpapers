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

from gi.repository import Soup
from BeautifulSoup import BeautifulStoneSoup

from gpapers.importer import SimpleWebSearchProvider
from gpapers.gPapers.models import Paper
from gpapers.logger import *

QUERY_STRING = 'http://dfr.jstor.org/sru/?version=1.1&' + \
                   'operation=searchRetrieve&query=%(query)s&' + \
                   'maximumRecords=%(max)d&' + \
                   'recordSchema=info:srw/schema/srw_jstor'


class JSTORSearch(SimpleWebSearchProvider):

    name = 'JSTOR'
    label = 'jstor'
    icon = 'favicon_jstor.ico'

    def __init__(self):
        SimpleWebSearchProvider.__init__(self)
        # TODO: Make this configurable
        self.max_results = 20

    def prepare_search_message(self, search_string):
        return Soup.Message.new(method='GET',
                                uri_string=QUERY_STRING % {'query': search_string,
                                                           'max' : self.max_results})

    def _parse_result(self, result):
        '''
        Parses a single result (a "swr:recorddata" in JSTOR's XML) and returns
        a dictionary with the info (title, authors, etc.).
        '''
        paper = {}
        authors = []
        for author in result.findAll('jstor:author'):
            if author:
                authors.append(author.string)
        if authors:
            paper['authors'] = authors

        # define mappings from the JSTOR names to our own keywords
        mappings = {'title': 'jstor:title',
                    'doi': 'jstor:id',
                    'abstract': 'jstor:abstract',
                    'journal': 'jstor:journaltitle',
                    'volume': 'jstor:volume',
                    'issue': 'jstor:issue',
                    'year': 'jstor:year',
                    'pages': 'jstor:pagerange',
                    'publisher': 'jstor:publisher'
                    }

        for our_key, jstor_key in mappings.items():
            try:
                paper[our_key] = result.find(jstor_key).string
            except:
                pass

        # The year is a string like "YEAR: 2012" in JSTOR
        if 'year' in paper:
            try:
                int(paper['year'])
            except ValueError:
                paper['year'] = paper['year'][-5:]

        return paper

    def parse_response(self, response):
        parsed = BeautifulStoneSoup(response)
        papers = []
        for result in parsed.find('srw:records').findAll('srw:record'):
            result = result.find('srw:recorddata')
            log_debug('Single result: %s' % result.prettify())

            paper = self._parse_result(result)

            log_debug('JSTOR paper info: %s' % str(paper))

            # Add the full data, useful for later import
            paper['data'] = result
            papers.append(paper)

        return papers

    def fill_in_paper_info(self, data):
        paper_info = self._parse_result(data)

        return paper_info
