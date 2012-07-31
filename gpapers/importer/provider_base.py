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

'''
This module contains the base class for all search providers
'''
from gi.repository import Soup

from gpapers.logger import log_info, log_debug
from gpapers.importer import soup_session
from gpapers.importer import active_threads

class WebSearchProvider(object):
    '''
    Base class for all web search providers, i.e. websites or web APIs that 
    return a number of search results for a search string.

    Implementation of new search providers should derive from this class and
    have to provide the following attributes as class attributes:
    
    `name`
        A human readable name that is used in the left column of the GUI,
        e.g. "Google Scholar".
    `label`
        A simple name that is used for saving searches to the database, 
        e.g. "gscholar"
    `icon`
        The name of an icon (expected in the `icons` subdirectory
        currently) used in the left column of the GUI, e.g.
        "favicon_google.ico". If no icon name is provided, a standard
        icon is used.
    `unique_key`
        Defining under what circumstances a search result should be
        considered a duplicate of an existing paper in the
        database. For a PubMED search, for example, this should be
        'pubmed_id'. If the unique key is not set, 'doi' is used
        as a default.

    In the simplest case (for the search, a single request to a website is 
    sufficient and that is all the data that is needed for an import), it is
    enough to overwrite two relatively simple methods (see
    :class:`importer.jstor.JSTORSearch` for an example):
    
    .. method:: prepare_search_message(self, search_string)
    
       Has to construct and return a `Soup.Message` object using
       `Soup.Message.new`.

    .. method:: parse_response(self, response):
    
       Receives the HTML response of the website and should return a list of
       paper info dictionaries (see :meth:`search_async`).

    For more complex scenarios, the following methods can be overwritten:
    
    .. method:: search_async(self, search_string, callback)
    
       This method receives a search string from the GUI and should call the
       callback with a list of paper info dictionaries (see :meth:`search_async`)
    
    .. method:: import_paper_after_search(self, paper, callback)
    
       This method receives the a :class:`VirtualPaper` object, already
       filled with the information previously returned from the search. It should
       call the callback when it is finished processing (which may include getting
       more information from webpages -- in this case the :class:`AsyncSoupSession`
       object `importer.soup_session` should be used to asynchronously fetch the 
       page(s)) (see :meth:`import_paper_after_search`). 
    
    In case that the website supports the downloading of multiple papers at
    once, it may also be more efficient to use this operation by overwriting
    :meth:`import_papers_after_search` which otherwise will call
    :meth:`import_paper_after_search` for each paper.
    
    Note that if the subclass overwrites the :meth:`__init__` method, it has
    to call the :meth:`__init__` of its superclass.        
    '''

    unique_key = 'doi'

    def __init__(self):
        '''
        Initializes the cache for previous search results (should be called
        by overriding implementations in subclasses).
        '''
        # Remember previous search results so that no new search is necessary.
        # Useful especially if switching between libraries/searches in the left
        # pane
        self.search_cache = {}

    def __str__(self):
        '''
        Return the name of this search provider.
        '''
        return self.name

    def clear_cache(self, text):
        '''
        Delete search results for `text` from the cache.
        '''
        if text in self.search_cache:
            del self.search_cache[text]

    def search_async(self, search_string, callback, error_callback):
        '''
        Asynchronously search for `search_string` and hand over a list of
        search results to the callback. Each single search result is a 
        dictionary containing all the information that could be fetched from the
        webpage, e.g.:
        ..
        
            [{'title': 'A paper title', 'authors': ['Author A', 'Author B']},
             {'title': 'Another paper', 'authors': ['Author C'],
              'import_url': 'http://example.com/paper.pdf'}]
              
        In addition, each paper can also contain arbitrary additional data as the 
        value for a 'data' key. This could for example be used to save the full
        HTML code of a search result (which might be useful for an import of this
        paper) as opposed to only the extracted information.
        This method should not block but use the :class:`AsyncSoupSession` object
        `importer.soup_session` for getting the information.
        ''' 

        try:
            # Call the method defined in the subclass
            message = self.prepare_search_message(search_string)

            def my_callback(session, message, user_data):
                self.handle_response_received(message, callback, error_callback)

            soup_session.queue_message(message, my_callback, None)
        except Exception as ex:
            error_callback(ex, search_string)

    def search(self, search_string, callback, error_callback):
        '''
        This method will be called by the GUI with the `search_string` when a
        search is initiated. Returns search results from the cache or initiates
        a new search using :meth:`search_async` if the search has not been
        performed before. Before calling the `callback`, saves the search
        results to the cache.
        
        This method should normally not be overwritten.
        '''
        # A tuple identifying the search, making it possible for the callback
        # function to deal with the results properly (otherwise results arriving
        # out of order could lead to wrongly displayed results)
        user_data = (self.label, search_string)

        if not search_string:
            callback(user_data, [])
            return

        if search_string in self.search_cache:
            log_debug('Result for "%s" already in cache.' % search_string)
            callback(user_data, self.search_cache[search_string])
            return

        log_info('Search for "%s" is not cached by this provider, starting new search' % search_string)

        try:
            def callback_wrapper(search_results):
                '''
                Before calling the actual callback, save the result in the
                cache and add `user_data` (tuple identifying request and search
                provider) to the call.
                '''
                log_debug('Saving %s in cache for "%s"' % (search_results, search_string))
                self.search_cache[search_string] = search_results
                callback(user_data, search_results)

            self.search_async(search_string, callback_wrapper, error_callback)
        except Exception as ex:
            error_callback(ex, None)
    
    def handle_response_received(self, message, callback, error_callback):
        '''
        Will be called when the server returns a response. If the server
        returns an invalid response, the error callback is called. In case of 
        a valid response, the response will be parsed with
        :meth`parse_respose` and the resulting list returned to the callback.
        '''
        if message.status_code == Soup.KnownStatusCode.OK:
            callback(self.parse_response(message.response_body.flatten().get_data()))
        else:
            error_callback(message.status_code, None)

    def import_papers_after_search(self, papers, callback):
        '''
        This method will be called if multiple `papers` are requested for import.
        In the default case, this imports one paper after the other calling
        :meth:`import_paper_after_search` for each individual paper (which in 
        turn calls the the `callback` for each result).
        Some search providers allow downloading multiple papers in one bulk
        operation, such providers should overwrite this function.
        '''
        identifier = '%s_%f' % (self.label, time.time()) #only used for status message
        
        def import_all_papers(paper_list):
            active_threads[identifier] = 'Importing %d papers' % len(paper_list)
            def my_callback(paper_obj=None, paper_data=None, paper_info=None,
                            user_data=None):
                
                callback(paper_obj=paper_obj, paper_data=paper_data,
                         paper_info=paper_info, user_data=user_data)
                import_all_papers(paper_list)
            
            if len(paper_list):
                one_paper = paper_list.pop()
                self.import_paper_after_search(one_paper, my_callback)
            else:
                if identifier in active_threads:
                    del active_threads[identifier]
        
        import_all_papers(papers)

    def import_paper_after_search(self, paper_obj, callback):
        '''
        This method is called when a search result is requested to be imported.
        The given `paper_obj` is a :class:`VirtualPaper` which has all the
        information previously returned by the search as attributes, e.g.
        `paper_obj.doi` is its DOI. The special attribute `data` should be used
        for information that can be useful for importing the paper, in addition
        to the default paper attributes. For example,
        :class:`GoogleScholarSearch` saves the complete HTML code for a search
        result, which contains a link to BibTeX data and possibly to a PDF
        document.
        
        If this method is not overwritten, it asynchronously downloads a
        document given in import_url (if any) and returns the original 
        `paper_obj` and possibly the PDF document to the callback. In case the
        search provider does not have any info to add to the initial search
        result, this is all that is needed. In cases where the search provider
        can add more information (e.g. the :class:`PubMedSearch` only requests
        summaries for the search, but when a specific paper is requested it
        gets the full record), this method should be overwritten.
        '''
        # in case the paper already had an import URL, download from this URL
        if hasattr(paper_obj, 'import_url') and paper_obj.import_url:
            message = Soup.Message.new(method='GET',
                                       uri_string=paper_obj.import_url)
            
            def mycallback(session, message, user_data):
                if message.status_code == Soup.KnownStatusCode.OK:
                    paper_data = message.response_body.flatten().get_data()
                    callback(paper_obj=paper_obj,
                             paper_data=paper_data,
                             user_data=user_data)
                else:
                    log_error("%: got status %s while trying to fetch PDF" % (self.__class__.__name__,
                                                                              message.status_code))
                    callback(paper_obj=paper_obj, user_data=user_data)
            
            log_debug("%s: trying to fetch %s" % (self.__class__.__name__,
                                                  paper_obj.import_url))
            soup_session.queue_message(message, mycallback,
                                       (self.label, paper_obj.import_url))
        else:
            callback(paper_obj=paper_obj, user_data=self.label)

    # -------------------------------------------------------------------------
    # Methods to overwrite in sub classes for the simple case, see class
    # documentation
    # -------------------------------------------------------------------------
    def prepare_search_message(self, search_string):
        '''
        If :meth:`search_async` is not overwritten, this method should be
        overwritten to return a :class:`Soup.Message`, representing the query
        that should be send to the website. In many cases, this is as simple as
        ::
        uri = 'http://example.com/search?query=%s' % search_string
        return Soup.Message.new(method='GET', uri_string=uri)
        
        '''         
        raise NotImplementedError()

    def parse_response(self, response):
        '''
        In case :meth:`handle_response_received` has not been overwritten,
        this method will be called to parse a response (typically HTML or XML).
        It is expected to return a list of search results (see
        :meth:`search_async` for further details).  
        '''
        raise NotImplementedError()
