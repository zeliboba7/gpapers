import urllib, traceback

from BeautifulSoup import BeautifulSoup
from django.template import defaultfilters

import openanything
from logger import log_debug, log_info, log_error
from importer import html_strip

class GoogleScholarSearch(object):

    def unique_key(self):
        return 'import_url'

    def search(self, search_text):
        '''
        Returns a list of dictionaries: The PUBMED results for the given search
        query
        '''
        if not search_text:
            return []

        papers = []
        try:
            query = 'http://scholar.google.com/scholar?q=%s' % defaultfilters.urlencode(search_text)
            log_debug('Starting google scholar search for query "%s"' % query)
            params = openanything.fetch(query)
            if params['status'] == 200 or params['status'] == 302:
                node = BeautifulSoup(params['data'],
                                     convertEntities=BeautifulSoup.HTML_ENTITIES)
                for result in node.findAll('div', attrs={'class' : 'gs_r'}):
                    paper = {}
                    #print '==========================================='

                    try:
                        title_node = result.findAll('h3', attrs={'class' : 'gs_rt'})[0]
                        #Can be a link or plain text
                        title_link = title_node.findAll('a')
                        if title_link:
                            log_debug('title_link: %s' % title_link[0].prettify())
                            paper['title'] = title_link[0].string
                            paper['import_url'] = title_link[0]['href']
                        else:
                            paper['title'] = title_node.string
                            paper['import_url'] = ''

                        if not paper['import_url'].startswith('http'):
                            paper['import_url'] = 'http://scholar.google.com' + paper['import_url']

                        try:
                            author_journal_publisher = result.findAll('div',
                                                     attrs={'class' : 'gs_a'})[0]
                            log_debug('Author string: %s' % str(author_journal_publisher.text))
                            authors, journal, publisher = author_journal_publisher.text.split(' - ')
                            paper['authors'] = authors.split(',')
                            journal_year = journal.split(',')
                            if len(journal_year) == 2:
                                paper['journal'] = journal_year[0]
                                paper['year'] = journal_year[1]
                            elif len(journal_year) == 1: # might be a year or a journal
                                try:
                                    paper['year'] = int(journal_year[0])
                                except ValueError:
                                    paper['journal'] = journal_year[0]
                            paper['publisher'] = publisher
                        except:
                            pass

                        try:
                            paper['abstract'] = html_strip(result.findAll('div', attrs='gs_rs')[0].string)
                        except:
                            pass
                    except:
                        traceback.print_exc()
                    papers.append(paper)

                return papers
            else:
                log_error('Google scholar replied with error code %d for query: %s' % \
                          (params['status'], search_text))
        except:
            traceback.print_exc()
