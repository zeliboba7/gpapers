import urllib

import BeautifulSoup

from logger import log_debug, log_info, log_error
from BeautifulSoup import BeautifulStoneSoup

from gPapers.models import *

BASE_URL = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
ESEARCH_QUERY = 'esearch.fcgi?db=pubmed&term=%s&usehistory=y'
ESUMMARY_QUERY = 'esummary.fcgi?db=pubmed&query_key=%s&WebEnv=%s'
EFETCH_QUERY = 'efetch.fcgi?db=pubmed&id=%s&retmode=xml'


class PubMedSearch(object):

    def __init__(self):
        self.search_cache = {}
        self.name = 'PubMed'
        self.label = 'pubmed'
        self.icon = 'favicon_pubmed.ico'

    def unique_key(self):
        return 'pubmed_id'

    def clear_cache(self, text):
        if text in self.search_cache:
            del self.search_cache[text]

    def search(self, search_text):
        '''
        Returns a list of dictionaries: The PUBMED results for the given search
        query
        '''
        if not search_text:
            return []  # Do not make empty queries

        if search_text in self.search_cache:
            return self.search_cache[search_text]

        # First do a query only for ids that is saved on the server
        log_debug('Starting Pubmed query for string "%s"' % search_text)
        query = BASE_URL + ESEARCH_QUERY % urllib.quote_plus(search_text)
        response = urllib.urlopen(query)
        if not (response.getcode() == 200 or response.getcode() == 302):
            log_error('Pubmed replied with error code %d for query: %s' % \
                      (response.getcode(), query))
            #TODO: Show a dialog or handle it differently?
            return []

        parsed_response = BeautifulSoup.BeautifulStoneSoup(response)

        # Check wether there were any hits at all
        if int(parsed_response.esearchresult.count.string) == 0:
            log_info('No hits for search string "%s"' % search_text)
            self.search_cache[search_text] = []
            return []

        web_env = parsed_response.esearchresult.webenv.string
        query_key = parsed_response.esearchresult.querykey.string
        response.close()

        # Download the summaries
        log_debug('Continuing Pubmed query (downloading summaries)')
        query = BASE_URL + ESUMMARY_QUERY % (query_key, web_env)
        response = urllib.urlopen(query)
        if not (response.getcode() == 200 or response.getcode() == 302):
            log_error('Pubmed replied with error code %d for query: %s' % \
              (response.getcode(), query))
        parsed_response = BeautifulSoup.BeautifulStoneSoup(response)

        # get information for all documents
        documents = parsed_response.esummaryresult.findAll('docsum')
        papers = []
        for document in documents:
            info = {}
            # Extract information
            info['pubmed_id'] = str(document.id.string)

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

        self.search_cache[search_text] = papers
        return papers

    def import_paper(self, data, paper=None):
        assert paper.pubmed_id
        log_info('Trying to import pubmed citation with id %s' % paper.pubmed_id)
        query = BASE_URL + EFETCH_QUERY % paper.pubmed_id
        try:
            response = urllib.urlopen(query)
            if not (response.getcode() == 200 or response.getcode() == 302):
                log_error('Pubmed replied with error code %d for query: %s' % \
                                  (response.getcode(), query))
                return paper
            parsed_response = BeautifulStoneSoup(response)

            # Journal
            try:
                journal = parsed_response.findAll('journal')[0]
                name = journal.findAll('title')[0].text
                log_debug('Journal name: %s' % name)
                try:
                    issue = journal.findAll('issue')[0].text
                except:
                    issue = ''
                log_debug('Journal issue: %s' % issue)
                #TODO: Volume etc
                source, created = Source.objects.get_or_create(name=name,
                                                               issue=issue)
                if created:
                    source.save()
                paper.source = source
                paper.source_pages = parsed_response.findAll('medlinepgn')[0].text
                log_debug('Pages: %s' % paper.source_pages)
            except Exception as ex:
                pass

            # Title and abstract
            try:
                paper.title = parsed_response.findAll('articletitle')[0].text
                log_debug('Title: %s' % paper.title)
                paper.abstract = parsed_response.findAll('abstracttext')[0].text
                log_debug('Abstract: %s' % paper.abstract)
            except Exception as ex:
                pass

            # Authors
            try:
                authors = parsed_response.findAll('author')
                for author in authors:
                    author_name = author.forename.text + ' ' + \
                                            author.lastname.text
                    log_debug('\tAuthor: %s' % author_name)
                    author_obj, created = Author.objects.get_or_create(name=author_name)
                    paper.authors.add(author_obj)
                    if created:
                        author_obj.save()
            except Exception as ex:
                traceback.print_stack()

        except Exception as ex:
            log_error('Downloading paper with id %s failed: %s' % \
                              (paper.pubmed_id, ex))

        return paper

    def __str__(self):
        return "PubMed"
