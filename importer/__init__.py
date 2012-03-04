#    gPapers
#    Copyright (C) 2007 Derek Anderson
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import commands, dircache, getopt, math, os, re, string, sys, thread, threading, time, traceback
from datetime import date, datetime, timedelta
from time import strptime
from htmlentitydefs import name2codepoint as n2cp
import urllib, urlparse

import gi
from gi.repository import GObject
from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Pango
from gi.repository import Soup

from pyPdf import PdfFileReader

from gPapers.models import *
from django.template import defaultfilters
import BeautifulSoup, openanything

from logger import *

active_threads = None

p_bibtex = re.compile('[@][a-z]+[\s]*{([^<]*)}', re.IGNORECASE | re.DOTALL)
p_whitespace = re.compile('[\s]+')
p_doi = re.compile('doi *: *(10.[a-z0-9]+/[a-z0-9.]+)', re.IGNORECASE)

soup_session = Soup.SessionAsync()


def latex2unicode(s):
    """
    *  \`{o} produces a grave accent
    * \'{o} produces an acute accent
    * \^{o} produces a circumflex
    * \"{o} produces an umlaut or dieresis
    * \H{o} produces a long Hungarian umlaut
    * \~{o} produces a tilde
    * \c{c} produces a cedilla
    * \={o} produces a macron accent (a bar over the letter)
    * \b{o} produces a bar under the letter
    * \.{o} produces a dot over the letter
    * \d{o} produces a dot under the letter
    * \u{o} produces a breve over the letter
    * \v{o} produces a "v" over the letter
    * \t{oo} produces a "tie" (inverted u) over the two letters
    """
    # TODO: expand this to really work
    return s.replace('\c{s}', u's')


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
    m = md5.new()
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


def get_or_create_paper_via(callback, id=None, doi=None, pubmed_id=None,
                            import_url=None, title=None, full_text_md5=None,
                            data=None, provider=None):
    """Tries to look up a paper by various forms of id, from most specific to
    least. Can also be used to fill in the data for a search result -- then
    data and search_provider have to be specified."""
    #print id, doi, pubmed_id, import_url, title, full_text_md5
    paper = None

    if id >= 0:
        try: paper = Paper.objects.get(id=id)
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

    if provider:
        # Get the paper from the search provider
        provider.import_paper_after_search(data, paper=paper, callback=callback)
    else:
        callback(paper)




def update_paper_from_bibtex_html(paper, html):

    # ieee puts <br>s in their bibtex
    html = html.replace('<br>', '\n')

    match = p_bibtex.search(html)
    if match:

        bibtex_lines = [ x.strip() for x in match.group(1).split('\n') ]
        bibtex = {}

        for x in bibtex_lines:
            i = x.find('=')
            if i > 0:
                k, v = x[:i].strip(), x[i + 1:].strip()
                bibtex[k.lower()] = latex2unicode(v.strip('"\'{},'))

        # fix for ACM's doi retardedness
        if bibtex.get('doi', '').startswith('http://dx.doi.org/'):
            bibtex['doi'] = bibtex['doi'][ len('http://dx.doi.org/'): ]
        if bibtex.get('doi', '').startswith('http://doi.acm.org/'):
            bibtex['doi'] = bibtex['doi'][ len('http://doi.acm.org/'): ]

        # create our paper if not provided for us
        if not paper:
            # FIXME
            paper, created = get_or_create_paper_via(doi=bibtex.get('doi'), title=bibtex.get('title'))
            if created:
                log_info('creating paper: %s' % str(paper))
            else:
                log_info('updating paper: %s' % str(paper))

        if bibtex.get('doi'): paper.doi = bibtex.get('doi', '')
        if bibtex.get('title'): paper.title = bibtex.get('title', '')
        if bibtex.get('source_pages'): paper.source_pages = bibtex.get('pages', '')
        if bibtex.get('abstract'): paper.abstract = bibtex.get('abstract', '')

        # search for author information
        if bibtex.get('author') and paper.authors.count() == 0:
            for author_name in bibtex['author'].split(' and '):
                author_name = author_name.strip()
                author, created = Author.objects.get_or_create(name=author_name)
                if created: author.save()
                paper.authors.add(author)

        # set publisher and source
        publisher_name = bibtex.get('publisher')
        if publisher_name:
            publisher, created = Publisher.objects.get_or_create(name=publisher_name)
            if created: publisher.save()
        else:
            publisher = None
        publication_date = None
        try: publication_date = date(int(bibtex.get('year')), 1, 1)
        except: pass
        source_name = None
        if not source_name and bibtex.get('booktitle'): source_name = bibtex['booktitle']
        if not source_name and bibtex.get('journal'): source_name = bibtex['journal']
        if source_name:
            source, created = Source.objects.get_or_create(
                name=source_name,
                issue=bibtex.get('booktitle', ''),
                location=bibtex.get('location', ''),
                publication_date=publication_date,
                publisher=publisher,
            )
            if created:
                source.save()
            paper.source = source


        paper.bibtex = match.group(0)
        paper.save()
        log_info('imported bibtex: %s' % bibtex)

    return paper


#TODO: Refactor import_pdf into a new function 
def import_citation(url, paper=None, callback=None):

    log_info('Importing URL: %s' % url)

    active_threads[ thread.get_ident() ] = 'importing: ' + url
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
                    if os.path.splitext(query[key])[1].lower() == '.pdf':
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
    if active_threads.has_key(thread.get_ident()):
        del active_threads[ thread.get_ident() ]

p_html_a = re.compile("<a [^>]+>" , re.IGNORECASE)
p_html_a_href = re.compile('''href *= *['"]([^'^"]+)['"]''' , re.IGNORECASE)


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


def find_and_attach_pdf(paper, urls, visited_urls=set()):

    # search for a PDF linked directly
    for url in urls:
        if url.find('?') > 0: url = url[ : url.find('?') ]
        if url.lower().endswith('pdf'):
            log_debug('found PDF link: %s' % url)
            visited_urls.add(url)
            params = openanything.fetch(url)
            if params['status'] == 200 or params['status'] == 302 :
                if params['data'].startswith('%PDF'):
                    # we have a live one!
                    try:
                        filename = params['url'][ params['url'].rfind('/') + 1 : ]
                        log_info('importing paper: %s' % filename)
                        paper.save_file(defaultfilters.slugify(filename.replace('.pdf', '')) + '.pdf', params['data'])
                        paper.save()
                        return True
                    except:
                        traceback.print_exc()

    for url in urls:
        visited_urls.add(url)
        params = openanything.fetch(url)
        if params['status'] == 200 or params['status'] == 302 :
            if params['data'].startswith('%PDF'):
                # we have a live one!
                try:
                    filename = params['url'][ params['url'].rfind('/') + 1 : ]
                    log_info('importing paper: %s' % filename)
                    paper.save_file(defaultfilters.slugify(filename.replace('.pdf', '')) + '.pdf', params['data'])
                    paper.save()
                    return True
                except:
                    traceback.print_exc()
            else:
                soup = BeautifulSoup.BeautifulSoup(params['data'])
                promising_links = set()
                for a in soup.findAll('a', href=True):
                    if len(a.contents) > 8: continue
                    web_dir_root = params['url'][: params['url'].find('/', 8) ]
                    web_dir_current = params['url'][: params['url'].rfind('/') ]
                    href = a['href']
                    if not href.lower().startswith('http'):
                        if href.startswith('/'):
                            href = web_dir_root + href
                        else:
                            href = web_dir_current + '/' + href
                    x = href
                    if x.find('?') > 0: x = x[ : x.find('?') ]
                    if x.lower().endswith('pdf'):
                        if href not in visited_urls:
                            log_info('found PDF link: %s' % a)
                            promising_links.add(href)
                            continue
                    for c in a.contents:
                        c = str(c).lower()
                        if c.find('pdf') != -1:
                            if href not in visited_urls:
                                log_info('found PDF link: %s' % a)
                                promising_links.add(href)
                                continue
                if promising_links: print promising_links
                if find_and_attach_pdf(paper, list(promising_links), visited_urls=visited_urls): return


def update_paper_from_dictionary(paper_info, paper):
    '''
    Adds all information from a `paper_info` dictionary to the given
    :class:`gPapers.model.Paper` object, creating and saving 
    :class:`gPapers.model.Author` and :class:`gPapers.model.Source` objects
    if necessary.
    
    Returns the `paper` object.
    '''
    assert paper is not None
    # Journal
    if 'journal' in paper_info:
        #TODO: Volume etc
        if 'issue' in paper_info:
            source, created = Source.objects.get_or_create(name=paper_info['journal'],
                                                           issue=paper_info['issue'])
        else:
            source, created = Source.objects.get_or_create(name=paper_info['journal'])
        if created:
            source.save()
        paper.source = source

    if 'pages' in paper_info:
        paper.source_pages = paper_info['pages']

    # Authors
    if 'authors' in paper_info:
        for author in paper_info['authors']:
            author_obj, created = Author.objects.get_or_create(name=author)
            paper.authors.add(author_obj)
            if created:
                author_obj.save()
    # Simple attributes
    attributes = ['title', 'abstract', 'year']

    for attr in attributes:
        if attr in paper_info:
            paper.__setattr__(attr, paper_info[attr])

    paper.save()
    return paper

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
    * `unique_keys`: Defining under what circumstances a search result should be
                     considered a duplicate of an existing paper in the
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
        
    * `import_paper_after_search(self, data, paper, callback, error_callback)`
    This method receives the `data` (if any) previously returned from the
    :method:`parse_website_response` method and a :class:`Paper` object, already
    filled with the information previously returned from the search. It should
    call the callback when it is finished processing (which may include getting
    more information from webpages -- in this case the :class:`AsyncSoupSession`
    object `importer.soup_session` should be used to asynchronously fetch the 
    page(s). The callback function has to be called with the same :class:`Paper`
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
        if not search_string:
            return []

        if search_string in self.search_cache:
            return self.search_cache[search_string]

        try:
            self.search_async(search_string, callback, error_callback)
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
    
    Such web search providers need only provide three functions:
    * prepare_search_message 
    * parse_response
    * fill_in_paper_info
    
    '''

    def __init__(self):
        WebSearchProvider.__init__(self)

    def search_async(self, search_string, callback, error_callback):
        try:
            # Call the method defined in the subclass
            message = self.prepare_search_message(search_string)

            def my_callback(session, message, user_data):
                self.response_received(message, callback, error_callback,
                                       user_data)

            # Provide a tuple of label and search string as `user_data` to the
            # callback -- this way it is clear to what search a result/error belongs
            soup_session.queue_message(message, my_callback, (self.label, search_string))
        except Exception as ex:
            error_callback(ex, search_string)

    def response_received(self, message, callback, error_callback,
                            user_data):
        '''
        Will be called when the server returns a response.
        '''
        log_info('Received a response for %s' % str(user_data))
        if message.status_code == Soup.KnownStatusCode.OK:
            #try:
                callback(user_data, self.parse_response(message.response_body.data))
            #except Exception as ex:
            #    error_callback(ex, user_data)
        else:
            error_callback(message.status_code, user_data)

    def import_paper_after_search(self, data, paper, callback):
        try:
            callback(self.fill_in_paper_info(data, paper))
        except Exception as ex:
            log_error(str(ex))

    # --------------------------------------------------------------------------
    # Methods to overwrite in sub classes
    # --------------------------------------------------------------------------
    def prepare_search_message(self, search_string):
        raise NotImplementedError()

    def parse_response(self, response):
        raise NotImplementedError()

    def fill_in_paper_info(self, data, paper=None):
        raise NotImplementedError()


class WebRessourceProvider(object):
    '''
    In addition to searching, a :class:`WebRessourceProvider` can provide
    information about a single paper, e.g. a PubMED provider can 
    provide paper data given a PubMED ID. A method gives information about its
    capabilities:
    * `provides_infos_for_attribute(self, attribute)`
    `attribute` is a string like 'pubmed_id'
    
    If the class return True for any attribute in the previous method (otherwise
    the class is pretty useless...), it has to provide another method:
    * `get_infos_for_attribute(self, paper, attribute, value, callback, error_callback)`        
    '''

    def provides_infos_for_attribute(self, attribute):
        return False
