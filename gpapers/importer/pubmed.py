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

import urllib

import BeautifulSoup
from BeautifulSoup import BeautifulStoneSoup
from gi.repository import Soup  # @UnresolvedImport

from gpapers.logger import log_debug, log_info, log_error
from gpapers.importer import soup_session
from gpapers.importer.provider_base import WebSearchProvider

BASE_URL = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
ESEARCH_QUERY = 'esearch.fcgi?db=pubmed&term=%s&usehistory=y'
ESUMMARY_QUERY = 'esummary.fcgi?db=pubmed&query_key=%s&WebEnv=%s'
EFETCH_QUERY = 'efetch.fcgi?db=pubmed&id=%s&retmode=xml'


class PubMedSearch(WebSearchProvider):

    name = 'PubMed'
    label = 'pubmed'
    icon = 'favicon_pubmed.ico'
    unique_key = 'pubmed_id'

    def __init__(self):
        WebSearchProvider.__init__(self)

    def _ids_received(self, message, callback, error_callback):

        if not message.status_code == Soup.KnownStatusCode.OK:
            error_callback('Pubmed replied with error code %d.' % message.status_code)
        else:
            response_data = message.response_body.flatten().get_data()
            parsed_response = BeautifulSoup.BeautifulStoneSoup(response_data)

            # Check whether there were any hits at all
            if int(parsed_response.esearchresult.count.string) == 0:
                return # Nothing to do anymore

            # Continue with a second request asking for the summaries
            web_env = parsed_response.esearchresult.webenv.string
            query_key = parsed_response.esearchresult.querykey.string
            log_debug('Continuing Pubmed query (downloading summaries)')
            query = BASE_URL + ESUMMARY_QUERY % (query_key, web_env)

            message = Soup.Message.new(method='GET', uri_string=query)

            def mycallback(session, message, user_data):
                self._summaries_received(message, callback, error_callback)

            soup_session.queue_message(message, mycallback, None)

    def _summaries_received(self, message, callback, error_callback):
        if not message.status_code == Soup.KnownStatusCode.OK:
            error_callback('Pubmed replied with error code %d.' % message.status_code)
        else:
            response_data = message.response_body.flatten().get_data()
            parsed_response = BeautifulSoup.BeautifulStoneSoup(response_data)

            # get information for all documents
            documents = parsed_response.esummaryresult.findAll('docsum')
            papers = []
            for document in documents:
                info = {}
                # Extract information
                info['pubmed_id'] = str(document.id.string)
                # This is needed for retrieving the paper in
                # import_paper_after_search
                info['data'] = info['pubmed_id']
                doi = document.findAll('item', {'name': 'doi'})
                if doi:
                    info['doi'] = doi[0].string
                    info['import_url'] = 'http://dx.doi.org/' + info['doi']

                info['title'] = document.findAll('item',
                                                 {'name': 'Title'})[0].string
                info['authors'] = [str(author.string) for author in \
                                          document.findAll('item',
                                                           {'name': 'Author'})]
                info['journal'] = document.findAll('item',
                                                  {'name': 'FullJournalName'})[0].string

                pubdate = document.findAll('item', {'name': 'PubDate'})
                if pubdate and pubdate[0]:
                    info['year'] = pubdate[0].string[:4]

                #TODO: Retrieve abstract

                papers.append(info)

            callback(papers)

    def search_async(self, search_text, callback, error_callback):
        '''
        Returns a list of dictionaries: The PUBMED results for the given search
        query
        '''

        # First do a query only for ids that is saved on the server
        log_debug('Starting Pubmed query for string "%s"' % search_text)
        query = BASE_URL + ESEARCH_QUERY % urllib.quote_plus(search_text)
        message = Soup.Message.new(method='GET', uri_string=query)

        def mycallback(session, message, user_data):
            self._ids_received(message, callback, error_callback)

        soup_session.queue_message(message, mycallback, None)

    def _paper_info_received(self, message, callback, user_data):
        if not message.status_code == Soup.KnownStatusCode.OK:
            log_error('Pubmed replied with error code %d for paper_info with id: %s' % \
                      (message.status_code, user_data[1]))
            paper_info = None
        else:
            parsed_response = BeautifulStoneSoup(message.response_body.data)
            paper_info = {}

            # Journal
            try:
                journal = parsed_response.findAll('journal')[0]
                paper_info['journal'] = journal.findAll('title')[0].text
                try:
                    paper_info['issue'] = journal.findAll('issue')[0].text
                except:
                    pass

                paper_info['pages'] = parsed_response.findAll('medlinepgn')[0].text
                log_debug('Pages: %s' % paper_info['pages'])
            except Exception as ex:
                pass

            # Publication date
            try:
                articledate = parsed_response.findAll('articledate')[0]
                paper_info['year'] = articledate.year.text
            except:
                pass

            # Title and abstract
            try:
                paper_info['title'] = parsed_response.findAll('articletitle')[0].text
                log_debug('Title: %s' % paper_info['title'])
                paper_info['abstract'] = parsed_response.findAll('abstracttext')[0].text
                log_debug('Abstract: %s' % paper_info['abstract'])
            except Exception as ex:
                pass

            # Authors
            try:
                all_authors = []
                authors = parsed_response.findAll('author')
                for author in authors:
                    author_name = author.forename.text + ' ' + \
                                            author.lastname.text
                    log_debug('\tAuthor: %s' % author_name)
                    all_authors.append(author_name)
                if all_authors:
                    paper_info['authors'] = all_authors
            except Exception as ex:
                pass

            # URL + IDs
            try:
                articleids = parsed_response.findAll('articleid')
                for articleid in articleids:
                    if articleid['idtype'] == 'doi':
                        paper_info['doi'] = articleid.text
                    elif articleid['idtype'] == 'pubmed':
                        paper_info['pubmed_id'] = articleid.text
            except:
                pass

        callback(paper_info=paper_info, user_data=user_data)

    def import_paper_after_search(self, paper, callback):
        pubmed_id = paper.data
        log_info('Trying to import pubmed citation with id %s' % pubmed_id)
        query = BASE_URL + EFETCH_QUERY % pubmed_id
        message = Soup.Message.new(method='GET', uri_string=query)

        def mycallback(session, message, user_data):
            self._paper_info_received(message, callback, user_data)

        soup_session.queue_message(message, mycallback,
                                   (self.label, pubmed_id))
