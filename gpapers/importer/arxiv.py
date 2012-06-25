#    gPapers
#    Copyright (C) 2007-2009 Derek Anderson
#                  2012      Derek Anderson, Marcel Stimberg, and Gordon Ball
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
import re
import datetime
import urllib

from gi.repository import Soup
import feedparser

from gpapers.importer import SimpleWebSearchProvider, soup_session
from gpapers.logger import log_debug, log_error

BASE_URL = 'http://export.arxiv.org/api/query?'
SORT_BY = "lastUpdatedDate"
SORT_ORDER = "descending"
MAX_RESULTS = 100

class ArxivSearch(SimpleWebSearchProvider):
    """
    A search provider/importer for the arXiv.org e-print archive,
    covering physics, mathematics, computer science, etc.
    
    Implements searches using the API documented at
    http://arxiv.org/help/api/user-manual
    """
    
    name = u'arXiv' #X -> \u03a7
    label = 'arxiv'
    icon = 'favicon_arxiv.ico'
    unique_key = 'import_url'
    
    def prepare_search_message(self, search_string):
        
        #if the query already uses arXiv syntax, don't add an
        #"all:" query on the front
        if not re.match("^(ti|au|abs|co|jr|cat|rn|id):\w+", search_string):
            search_string = 'all:' + search_string
        
        uri_string = BASE_URL + urllib.urlencode({'sortBy': SORT_BY,
                                                  'sortOrder': SORT_ORDER,
                                                  'max_results': MAX_RESULTS,
                                                  'search_query': search_string})
        
        log_debug("arxiv: requesting %s" % uri_string)
        return Soup.Message.new(method='GET', uri_string=uri_string)
    
    def parse_response(self, response):
        """
        Parse the arXiv response, which is in Atom XML format.
        
        The feed provides itself provides more-or-less all the
        information required without needing any extra requests.
        """
        
        papers = []
        try:
            parsed = feedparser.parse(response)
        except Exception as ex:
            log_error("arxiv: error while parsing response: %s" % ex[0])
            return papers
        
        log_debug("arxiv: received response containing %d results" % len(parsed.entries))    
        for entry in parsed.entries:
            paper = {}
            
            try:
                paper['title'] = entry['title']
                for link in entry['links']:
                    if link.get('title', None) == 'pdf':
                        paper['import_url'] = link['href']
                        break
                    
                paper['authors'] = [a['name'] for a in entry['authors']]
                if 'arxiv_journal_ref' in entry:
                    paper['journal'] = entry['arxiv_journal_ref']
                if 'arxiv_doi' in entry:
                    paper['doi'] = entry['arxiv_doi']
                if 'arxiv_comment' in entry:
                    paper['notes'] = entry['arxiv_comment']
                paper['year'] = entry['published_parsed'].tm_year
                paper['arxiv_id'] = entry['id']
                paper['url'] = entry['id']
                paper['abstract'] = entry['summary'].replace('\n', ' ')
                if 'arxiv_primary_category' in entry:
                    paper['arxiv_type'] = entry['arxiv_primary_category'].get('term', '')
                
                paper['created'] = datetime.datetime(year=entry['published_parsed'].tm_year,
                                                     month=entry['published_parsed'].tm_mon,
                                                     day=entry['published_parsed'].tm_mday)
                paper['updated'] = datetime.datetime(year=entry['updated_parsed'].tm_year,
                                                     month=entry['updated_parsed'].tm_mon,
                                                     day=entry['updated_parsed'].tm_mday)
                
                paper['data'] = paper #messy
                
                papers += [paper]
            except Exception as ex:
                log_error("arxiv: error while reading item: %s" % ex[0])
        
        return papers
    
    def import_paper_after_search(self, data, callback):
        """
        FIXME: Inconsistent signature for this function.
        
        gpapers.__init__:1702
        button.connect('clicked',
                               lambda x: paper.provider.import_paper_after_search(paper.data,
                                                                                  self.document_imported))
        
        gpapers.importer.__init__:625
        def import_paper_after_search(self, data, paper, callback)
        
        Nowehere appears to call the latter form, but it seems more sensible - 
        otherwise I have to set paper['data'] = paper otherwise I don't seem to
        be able to return appropriate info to the callback.
        
        I am not clear on the correct delegation of operations here - "import_url"
        is already supplied by the initial search operation, but it appears
        necessary to download it ourselves here or it doesn't get done.
        
        Note that arxiv returns 403 forbidden if no user-agent is set.
        """
        
        if 'import_url' in data:
            message = Soup.Message.new(method='GET', uri_string=data['import_url'])
            
            def mycallback(session, message, user_data):
                if message.status_code == Soup.KnownStatusCode.OK:
                    log_debug("arxiv: received pdf length %s" % message.response_body.length)
                    callback(data, message.response_body.flatten().get_data(), user_data)
                else:
                    log_error("arxiv: got status %s while trying to fetch PDF" % (message.status_code))
                    callback(data, None, user_data)
            
            log_debug("arxiv: trying to fetch %s" % data['import_url'])
            soup_session.queue_message(message, mycallback, (self.label, data['arxiv_id']))
        else:
            callback(data, None, self.label)