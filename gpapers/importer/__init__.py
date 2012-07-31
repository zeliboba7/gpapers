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
import time
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

import gpapers
from gpapers_info import __version__
from gpapers.logger import *
from gpapers.gPapers.models import Paper

active_threads = None

p_whitespace = re.compile('[\s]+')
p_doi = re.compile('doi *: *(10.[a-z0-9]+/[a-z0-9.]+)', re.IGNORECASE)

soup_session = Soup.SessionAsync()
#arXiv disallows requests if no user-agent is set
soup_session.set_property("user-agent", "gPapers/%s" % __version__)


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
    :func:`import_from_urls` will be called with this link. Finally, the
    callback is called with the `paper_info` (a dictionary) and `paper_data`
    (binary data) as an argument.
    '''
    
    active_threads[url] = 'Importing %s' % url

    def data_received(session, message, user_data):        
        
        if not message.status_code == Soup.KnownStatusCode.OK:
            # FIXME: Use error handler here
            log_warn('URL %s responded with error code %d' % (user_data,
                                                              message.status_code))
            if url in active_threads: 
                del active_threads[url]
            callback(user_data=user_data)
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
            if url in active_threads: 
                del active_threads[url]
            callback(paper_info=paper_info, paper_data=data, user_data=user_data)
        elif (content_type == 'text/x-bibtex' or first_letter == '@') and not paper_info:
            if url in active_threads: 
                del active_threads[url]
            callback(paper_info=bibtex.paper_info_from_bibtex(data),
                     paper_data=paper_data, user_data=user_data)
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
                if url in active_threads: 
                    del active_threads[url]
                import_from_urls(urls, callback, user_data)
            else:
                log_warn('Nothing found...')
                if url in active_threads: 
                    del active_threads[url]
                callback(paper_info=paper_info, paper_data=paper_data,
                         user_data=user_data)
        else:
            log_warn('Do not know what to do with content type %s of URL %s' % (content_type, orig_url))
            if url in active_threads: 
                del active_threads[url]
            callback(paper_info=paper_info, paper_data=paper_data, user_data=user_data)

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
        if url in active_threads: 
            del active_threads[url]
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

        if content_type.startswith('application/pdf') and not paper_data:
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
        callback(user_data=user_data)

    log_info(('Starting to look for PDF and/or metadata '
             'from %d possible URLs' % len(urls)))

    def _import_from_urls_finished(paper_info, paper_data, user_data):
        log_debug('_import_from_urls_finished')
        callback(paper_info=paper_info, paper_data=paper_data,
                 user_data=user_data)

    _import_from_urls(urls, _import_from_urls_finished, user_data)
