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

import os
import re
import traceback
from htmlentitydefs import name2codepoint as n2cp
import urllib
import urlparse
import hashlib

from gi.repository import Gio
from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Soup
from django.template import defaultfilters
import BeautifulSoup

from gpapers.logger import *
from gpapers.gPapers.models import Paper

active_threads = None

p_whitespace = re.compile('[\s]+')
p_doi = re.compile('doi *: *(10.[a-z0-9]+/[a-z0-9.]+)', re.IGNORECASE)

soup_session = Soup.SessionAsync()


def _decode_htmlentities(string):
    entity_re = re.compile("&(#?)(\d{1,5}|\w{1,8});")
    return entity_re.subn(_substitute_entity, string)[0]


def html_strip(s):
    if isinstance(s, BeautifulSoup.Tag):
        s = ''.join([ html_strip(x) for x in s.contents ])
    return _decode_htmlentities(p_whitespace.sub(' ', str(s).replace('&nbsp;', ' ').strip()))


def pango_escape(s):
    return s.replace('&', '&amp;').replace('>', '&gt;').replace('<', '&lt;')


def get_md5_hexdigest_from_data(data):
    m = hashlib.md5()
    m.update(data)
    return m.hexdigest()


def _substitute_entity(match):
    ent = match.group(2)
    if match.group(1) == "#":
        return unichr(int(ent))
    else:
        cp = n2cp.get(ent)

        if cp:
            return unichr(cp)
        else:
            return match.group()


def get_or_create_paper_via(paper_obj, callback, full_text_md5=None):

    paper_id = paper_obj.id
    doi = paper_obj.doi
    pubmed_id = paper_obj.pubmed_id
    import_url = paper_obj.import_url
    title = paper_obj.title
    provider = paper_obj.provider
    data = paper_obj.data

    paper = None

    if paper_id >= 0:
        try: paper = Paper.objects.get(id=paper_id)
        except: pass

    if doi:
        if paper:
            if not paper.doi:
                paper.doi = doi
        else:
            try: paper = Paper.objects.get(doi=doi)
            except: pass

    if pubmed_id:
        if paper:
            if not paper.pubmed_id:
                paper.pubmed_id = pubmed_id
        else:
            try: paper = Paper.objects.get(pubmed_id=pubmed_id)
            except: pass

    if import_url:
        if paper:
            if not paper.import_url:
                paper.import_url = import_url
        else:
            try: paper = Paper.objects.get(import_url=import_url)
            except: pass

    if full_text_md5:
        if not paper:
            try: paper = Paper.objects.get(full_text_md5=full_text_md5)
            except: pass

    if title:
        if paper:
            if not paper.title:
                paper.title = title
        else:
            try: paper = Paper.objects.get(title=title)
            except: pass

    if not paper:
        # it looks like we haven't seen this paper before...
        if provider:
            # Get the paper from the search provider
            provider.import_paper_after_search(data, callback=callback)
        else:
            if not doi:
                doi = ''
            if not pubmed_id:
                pubmed_id = ''
            if not import_url:
                import_url = ''
            if not title:
                title = ''
            paper = Paper.objects.create(doi=doi, pubmed_id=pubmed_id,
                                         import_url=import_url, title=title)
            # we are done, call the callback
            callback(paper)


#TODO: Refactor import_pdf into a new function 
def import_citation(url, paper=None, callback=None):

    log_info('Importing URL: %s' % url)

    active_threads[ str(thread.get_ident()) ] = 'importing: ' + url
    try:
        response = urllib.urlopen(url)
        if response.getcode() != 200 and response.getcode() != 302:
            log_error('unable to download: %s  (%i)' % (url, response.getcode()))
            return

        data = response.read(-1)
        info = response.info()

        if info.gettype() == 'application/pdf' or info.gettype() == 'application/octet-stream':
            # this is hopefully a PDF file                     

            #Try finding a PDF file name in the url
            parsed_url = urlparse.urlsplit(url)
            filename = os.path.split(parsed_url.path)[1]

            if os.path.splitext(filename)[1].lower() != '.pdf':
                filename = None
                #That didn't work, try to find a filename in the query string
                query = urlparse.parse_qs(parsed_url.query)
                for key in query:
                    print key, query[key]
                    if os.path.splitext(query[key][0])[1].lower() == '.pdf':
                        filename = query[key].lower() # found a .pdf name
                        break

            log_info('importing paper: %s' % filename)

            if not paper:
                md5_hexdigest = get_md5_hexdigest_from_data(data)
                # FIXME
                paper, created = get_or_create_paper_via(full_text_md5=md5_hexdigest)
                if created:
                    if not filename:
                        filename = md5_hexdigest # last resort for filename

                    paper.save_file(defaultfilters.slugify(filename.replace('.pdf', '')) + '.pdf',
                                    data)
                    paper.import_url = response.geturl()
                    paper.save()
                    log_info('imported paper: %s' % filename)
                else:
                    log_info('paper already exists: %s' % str(paper))
            else:
                paper.save_file(defaultfilters.slugify(filename.replace('.pdf', '')) + '.pdf',
                                 local_file.read())
                paper.import_url = response.geturl()
                paper.save()
            return paper

        # let's see if there's a pdf somewhere in here...
        paper = _import_unknown_citation(data, response.geturl(), paper=paper)
        if paper and callback:callback()
        if paper: return paper

    except:
        traceback.print_exc()
        Gdk.threads_enter()
        error = Gtk.MessageDialog(type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, flags=Gtk.DialogFlags.MODAL)
        error.connect('response', lambda x, y: error.destroy())
        error.set_markup('<b>Unknown Error</b>\n\nUnable to download this resource.')
        error.run()
        Gdk.threads_leave()

    Gdk.threads_enter()
    error = Gtk.MessageDialog(type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, flags=Gtk.DialogFlags.MODAL)
    error.connect('response', lambda x, y: error.destroy())
    error.set_markup('<b>No Paper Found</b>\n\nThe given URL does not appear to contain or link to any PDF files. (perhaps you have it buy it?) Try downloading the file and adding it using "File &gt;&gt; Import..."\n\n%s' % pango_escape(url))
    error.run()
    Gdk.threads_leave()
    if active_threads.has_key(str(thread.get_ident())):
        del active_threads[str(thread.get_ident())]


def _import_unknown_citation(data, orig_url, paper=None):

    # soupify
    soup = BeautifulSoup.BeautifulSoup(data)

    # search for bibtex link
    for a in soup.findAll('a'):
        for c in a.contents:
            if str(c).lower().find('bibtex') != -1:
                log_debug('found bibtex link: %s' % a)
                #TODO: Do something with bibtex link

    # search for ris link
    for a in soup.findAll('a'):
        if not a.has_key('href'):
            continue
        href = a['href']
        if href.find('?') > 0: href = href[ : href.find('?') ]
        if href.lower().endswith('.ris'):
            log_debug('found RIS link: %s' % a)
            break
        for c in a.contents:
            c = str(c).lower()
            if c.find('refworks') != -1 or c.find('procite') != -1 or c.find('refman') != -1 or c.find('endnote') != -1:
                log_debug('found RIS link: %s' % a)
                #TODO: Do something with ris link

    # search for pdf link
    # TODO: If more than one link is found, present the choice to the user
    pdf_link = None
    for a in soup.findAll('a'):
        if pdf_link:
            break
        if not a.has_key('href'):
            continue
        href = a['href']
        if href.lower() == orig_url.lower(): #this is were we came from...
            continue
        if href.find('?') > 0: href = href[ : href.find('?') ]
        if href.lower().endswith('pdf'):
            pdf_link = a['href']
            log_debug('found PDF link: %s' % a)
            break
        for c in a.contents:
            c = str(c).lower()
            if c.find('pdf') != -1:
                log_debug('found PDF link: %s' % a)
                pdf_link = a['href']
                break

    if pdf_link:
        #Combine the base URL with the PDF link (necessary for relative URLs)
        pdf_link = urlparse.urljoin(orig_url, pdf_link)
        return import_citation(pdf_link)


def get_bibtex_for_doi(doi, callback):
    '''
    Asynchronously retrieves the bibtex data for a document with a given `doi`,
    querying the crossref service. The `callback` function will be called with
    two arguments, a string containing the bibtex data and the doi for which
    the data was retrieved. In case of a failed retrieval, callback will be
    called with `None` for the bibtex data.
    '''
    url = 'http://dx.doi.org/' + doi
    message = Soup.Message.new(method='GET', uri_string=url)
    # Request BibTeX data instead of a redirect to the document URL
    message.request_headers.append('Accept', 'text/bibliography; style=bibtex')

    def mycallback(session, message, user_data):
        if message.status_code == Soup.KnownStatusCode.OK:
            bibtex = message.response_body.flatten().get_data()
            callback(bibtex, user_data)
        else:
            callback(None, user_data)

    # Use the doi as user_data for the callback
    soup_session.queue_message(message, mycallback, doi)


def determine_content_type(filename):
    '''
    Determines the content type for a file. Returns either a string like
    'application/pdf' or None if the type could not be determined. For files
    with a file extension, this function normally does only look at the
    filename, but if this is not sufficient for determining the content-type,
    the file can also be opened.
    '''

    # Try the fast content type first
    gfile = Gio.file_new_for_path(filename)
    info = gfile.query_info(Gio.FILE_ATTRIBUTE_STANDARD_FAST_CONTENT_TYPE,
                            Gio.FileQueryInfoFlags.NONE, None)
    content_type = info.get_attribute_as_string(Gio.FILE_ATTRIBUTE_STANDARD_FAST_CONTENT_TYPE)

    # If that did not work, try the full content-type determination
    if Gio.content_type_is_unknown(content_type):
        info = gfile.query_info(Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE,
                                Gio.FileQueryInfoFlags.NONE, None)
        content_type = info.get_attribute_as_string(Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE)

    if Gio.content_type_is_unknown(content_type):
        content_type = None

    return content_type


def import_from_url(url, callback, paper_info=None, paper_data=None):
    '''
    Searches the given url (asynchronously) for a PDF and/or metadata
    (currently it will only look for BibTeX data). If the URL is a standard
    HTML page, it will be searched for potential links, then 
    :function:`import_from_urls` will be called with this link. Finally, the
    callback is called with the `paper_info` (a dictionary) and `paper_data`
    (binary data) as an argument.
    '''

    def data_received(session, message, user_data):
        if not message.status_code == Soup.KnownStatusCode.OK:
            # FIXME: Use error handler here
            log_warn('URL %s responded with error code %d' % (user_data,
                                                              message.status_code))
            callback(None, None, user_data)
            return

        log_debug('Response received (status code OK)')

        content_type = message.response_headers.get_one('content-type').split(';')[0]
        log_debug('Content type determined')
        orig_url = message.get_uri().to_string(False)

        if message.response_body.data:
            data = message.response_body.flatten().get_data()
            # Heuristic: BibTeX data starts with a @            
            first_letter = data.strip()[0]
        else:
            first_letter = None
            data = None

        log_debug('Received content type %s for URI %s' % (content_type,
                                                           message.get_uri()))

        if content_type == 'application/pdf':
            callback(paper_info, data, user_data)
        elif (content_type == 'text/x-bibtex' or first_letter == '@') and not paper_info:
            callback(bibtex.paper_info_from_bibtex(data), paper_data, user_data)
        elif content_type == 'text/html':
            log_debug('Searching page for links')
            parsed = BeautifulSoup.BeautifulSoup(data)

            # Check all links
            urls = []
            for a in parsed.findAll('a'):
                if not a.has_key('href'):
                    continue
                href = a['href']
                if href.lower() == orig_url.lower(): #this is were we came from...
                    continue

                # Check for PDF links
                if href.lower().endswith('.pdf'):
                    urls.append(href)
                    log_debug('found potential PDF link: %s' % href)
                else:
                    for c in a.contents:
                        c = str(c).lower()
                        if 'pdf' in c:
                            urls.append(href)
                            log_debug('found potential PDF link: %s' % href)
                            break

                # Check for BibTeX links
                if href.lower().endswith('.bib'):
                    urls.append(href)
                    log_debug('found potential BibTeX link: %s' % href)
                else:
                    for c in a.contents:
                        c = str(c).lower()
                        if 'bibtex' in c:
                            urls.append(href)
                            log_debug('found potential BibTeX link: %s' % href)
                            break
            if urls:  # we found at least something...
                #Combine the base URL with the PDF link (necessary for relative URLs)
                urls = [urlparse.urljoin(orig_url, url) for url in urls]
                log_debug('Calling import_from_urls with %s' % str(urls))
                import_from_urls(urls, callback, user_data)
            else:
                log_warn('Nothing found...')
                callback(paper_info, paper_data, user_data)
        else:
            log_warn('Do not know what to do with content type %s of URL %s' % (content_type, orig_url))
            callback(paper_info, paper_data, user_data)

    try:
        message = Soup.Message.new(method='GET', uri_string=url)
        log_debug('Message generated')
    except TypeError as ex:
        log_error(str(ex))
        message = None

    if message:
        soup_session.queue_message(message, data_received, url)
        log_debug('Message queued')
    else:
        callback(paper_info, paper_data, url)


def _import_from_urls(urls, callback, user_data, paper_info=None, paper_data=None):
    '''
    Searches the given urls (asynchronously) for a PDF and/or metadata
    (currently it will only look for BibTeX data). When either all URLs have
    been searched or both metadata and PDF have been found, the callback is 
    called with the `paper_info` (a dictionary) and `paper_data` (binary data)
    as an argument.
    '''
    log_debug('_import_from_urls')
    if not urls or (paper_info and paper_data):
        callback(paper_info, paper_data, user_data)
        return

    url = urls.pop()

    def data_received(session, message, user_data):
        content_type = message.response_headers.get_one('content-type')
        if message.response_body.data:
            # Heuristic: BibTeX data starts with a @
            first_letter = message.response_body.data.strip()[0]
            log_debug('First letter of Body is: %s' % first_letter)
            data = message.response_body.flatten().get_data()
        else:
            first_letter = None
            data = None
        log_debug('Received content type %s for URI %s' % (content_type,
                                                           message.get_uri()))

        if content_type == 'application/pdf' and not paper_data:
            _import_from_urls(urls, callback, user_data, paper_info=paper_info,
                              paper_data=data)
        elif (content_type == 'text/x-bibtex' or first_letter == '@') and not paper_info:
            # TODO: Convert bibtex data
            new_paper_info = bibtex.paper_info_from_bibtex(data)
            _import_from_urls(urls, callback, user_data, paper_info=new_paper_info,
                              paper_data=paper_data)
        else: # Continue searching for usable data
            _import_from_urls(urls, callback, user_data, paper_info=paper_info,
                              paper_data=paper_data)

    message = Soup.Message.new(method='GET', uri_string=url)
    soup_session.queue_message(message, data_received, user_data)


def import_from_urls(urls, callback, user_data):
    '''
    Searches the given urls (asynchronously) for a PDF and/or metadata
    (currently it will only look for BibTeX data). When either all URLs have
    been searched or both metadata and PDF have been found, the callback is 
    called with the `paper_info` (a dictionary) and `paper_data` (binary data)
    as an argument.
    '''
    if urls is None:
        callback(None, None, user_data)

    log_info(('Starting to look for PDF and/or metadata '
             'from %d possible URLs' % len(urls)))

    def _import_from_urls_finished(paper_info, paper_data, user_data):
        log_debug('_import_from_urls_finished')
        callback(paper_info, paper_data, user_data)

    _import_from_urls(urls, _import_from_urls_finished, user_data)


class WebSearchProvider(object):
    '''
    Base class for all web search providers, i.e. websites or web APIs that 
    return a number of search results for a search string.

    Implementation of new search providers should derive from this class and
    have to provide the following attributes as class attributes:
    * `name`: A human readable name that is used in the left column of the GUI,
              e.g. "Google Scholar".
    * `label`: A simple name that is used for saving searches to the database, 
               e.g. "gscholar"
    * `icon` : The name of an icon (expected in the `icons` subdirectory
               currently) used in the left column of the GUI, e.g.
               "favicon_google.ico". If no icon name is provided, a standard
               icon is used.
    * `unique_key`: Defining under what circumstances a search result should be
                    onsidered a duplicate of an existing paper in the
                    database. For a PubMED search, for example, this should be
                    'pubmed_id'. If the unique key is not set, 'doi' is used
                    as a default.


    A search provider has to provide the following methods:
    * `search_async(self, search_string, callback)`
    This method receives a search string from the GUI and should call the
    callback with a list of search results where each single result is a
    dictionary containing all the information that could be fetched from the
    webpage, e.g.:
    [{'title': 'A paper title', 'authors': ['Author A', 'Author B']},
     {'title': 'Another paper', 'authors': ['Author C'],
      'import_url': 'http://example.com/paper.pdf'}]
    In addition, each paper can also contain arbitrary additional data as the 
    value for a 'data' key. This could for example be used to save the full
    HTML code of a search result (which might be useful for an import of this
    paper) as opposed to only the extracted information.
    This method should not block but use the :class:`AsyncSoupSession` object
    `importer.soup_session` for getting the information. 

    * `import_paper_after_search(self, data, paper, callback)`
    This method receives the `data` (if any) previously returned from the
    :method:`search_async` method and a :class:`Paper` object, already
    filled with the information previously returned from the search. It should
    call the callback when it is finished processing (which may include getting
    more information from webpages -- in this case the :class:`AsyncSoupSession`
    object `importer.soup_session` should be used to asynchronously fetch the 
    page(s)). The callback function has to be called with the same :class:`Paper`
    object (with any additional information now available filled in, generated
    :class:`Author` objects, etc.) as the first argument. Optionally, a list of
    URL strings can be given as the second argument, these URLs will be used 
    in the order they are given, i.e. if fetching the document from the first
    one is not successful, the second one will be tried etc. 

    The :method:`__init__` method of the subclass has to call the 
    :method:`__init__` method of the superclass.   
    '''

    unique_key = 'doi'

    def __init__(self):
        # Remember previous search results so that no new search is necessary.
        # Useful especially if switching between libraries/searches in the left
        # pane
        self.search_cache = {}

    def __str__(self):
        return self.name

    def clear_cache(self, text):
        if text in self.search_cache:
            del self.search_cache[text]

    def search(self, search_string, callback, error_callback):

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

    def import_paper_after_search(self, data, paper, callback):
        raise NotImplementedError()

    def search_async(self, search_string, callback, error_callback):
        raise NotImplementedError()

class SimpleWebSearchProvider(WebSearchProvider):
    '''
    Convenience class for web searches that do a single request to a website for
    a search and do not have to perform additional web requests to get more 
    detailed info for a paper chosen for import.

    Such web search providers need only to provide two simple functions 
    (see :class:`importer.jstor.JSTORSearch` for an example):
    * prepare_search_message(self, search_string)
          Has to construct and return a `Soup.Message` object using
          `Soup.Message.new`, for example:
          ..                     
              return Soup.Message.new(method='GET',
                                      uri_string='http://example.com/search?query=search_string')  

    * parse_response(self, response):
      Receives the HTML response of the website and should return a paper info
      dictionary (see :class:`WebSearchProvider`).
    '''

    def __init__(self):
        WebSearchProvider.__init__(self)

    def search_async(self, search_string, callback, error_callback):
        try:
            # Call the method defined in the subclass
            message = self.prepare_search_message(search_string)

            def my_callback(session, message, user_data):
                self.response_received(message, callback, error_callback)

            soup_session.queue_message(message, my_callback, None)
        except Exception as ex:
            error_callback(ex, search_string)

    def response_received(self, message, callback, error_callback):
        '''
        Will be called when the server returns a response.
        '''
        if message.status_code == Soup.KnownStatusCode.OK:
            #try:
                callback(self.parse_response(message.response_body.flatten().get_data()))
            #except Exception as ex:
            #    error_callback(ex, user_data)
        else:
            error_callback(message.status_code, None)

    def import_paper_after_search(self, data, paper, callback):
        # Nothing to add
        callback(paper, [], self.label)

    # -------------------------------------------------------------------------
    # Methods to overwrite in sub classes
    # -------------------------------------------------------------------------
    def prepare_search_message(self, search_string):
        raise NotImplementedError()

    def parse_response(self, response):
        raise NotImplementedError()
