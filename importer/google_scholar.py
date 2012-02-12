import urllib, traceback, thread

from BeautifulSoup import BeautifulSoup
from django.template import defaultfilters

import openanything
from logger import log_debug, log_info, log_error
from importer import html_strip, update_paper_from_bibtex_html, find_and_attach_pdf

BASE_URL = 'http://scholar.google.com'


class GoogleScholarSearch(object):

    def __init__(self):
        # set our google scholar prefs (cookie-based)
        #FIXME: This is blocking...
        log_debug('Google Scholar: Trying to set a cookie so that we get 100 results and bibtex links')
        #FIXME: Does not seem to work...
        params = openanything.fetch(BASE_URL + \
                           '/scholar_setprefs?num=100&scis=yes&scisf=4&submit=Save+Preferences')
        log_debug('Google Scholar: Returned status: %d' % params['status'])

        # Remember previous search results so that no new search is necessary.
        # Useful especially if switching between libraries/searches in the left
        # pane
        self.search_cache = {}

    def unique_key(self):
        return 'import_url'

    def search(self, search_text):
        '''
        Returns a list of dictionaries: The PUBMED results for the given search
        query
        '''
        if not search_text:
            return []

        if search_text in self.search_cache:
            return self.search_cache[search_text]

        papers = []
        try:
            query = BASE_URL + '/scholar?q=%s' % \
                            defaultfilters.urlencode(search_text)
            log_info('Starting google scholar search for query "%s"' % query)
            params = openanything.fetch(query)
            if params['status'] == 200 or params['status'] == 302:
                node = BeautifulSoup(params['data'],
                                     convertEntities=BeautifulSoup.HTML_ENTITIES)
                for result in node.findAll('div', attrs={'class': 'gs_r'}):
                    paper = {}
                    #print '==========================================='

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
                                                     attrs={'class' : 'gs_a'})[0]
                            log_debug('Author string: %s' % \
                                             str(author_journal_publisher.text))
                            authors, journal, publisher = \
                                      author_journal_publisher.text.split(' - ')
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
                            paper['abstract'] = html_strip(result.findAll('div', attrs='gs_rs')[0].text)
                        except:
                            pass

                        # Also attach the html data so it can be used later for
                        # importing the document
                        paper['data'] = result
                    except:
                        traceback.print_exc()
                    papers.append(paper)

                self.search_cache[search_text] = papers
                return papers
            else:
                log_error('Google scholar replied with error code %d for query: %s' % \
                          (params['status'], search_text))
        except:
            traceback.print_exc()

    def import_paper(self, data, paper=None):
        log_info('Trying to import google scholar citation "%s"' % paper.title)
        try:
            citations = data.findAll('div', {'class': 'gs_fl'})[0]
            log_debug('Citations: %s' % str(citations))
            for link in citations.findAll('a'):
                log_debug('Link: %s' % str(link))
                if link['href'].startswith('/scholar.bib'):
                    log_debug('Found BibTex link: ', link['href'])
                    data_bibtex = openanything.fetch(BASE_URL + link['href'])
                    if data_bibtex['status'] == 200 or data_bibtex['status'] == 302:
                        paper = update_paper_from_bibtex_html(paper, data_bibtex['data'])
                    return
            link = data.findAll('div', {'class': 'gs_ggs gs_fl'})[0]
            find_and_attach_pdf(paper, urls=[x['href'] for x in link.findAll('a') ])

            return paper
        except:
            traceback.print_exc()

    def __str__(self):
        return "Google Scholar"
