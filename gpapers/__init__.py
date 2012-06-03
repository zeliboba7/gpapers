#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

import commands
from datetime import datetime, timedelta, date
import math
import mimetypes
import os
import sys
import thread
import threading
import time
import traceback

from gi.repository import Gio
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import GdkPixbuf
from gi.repository import Pango
from gi.repository import Poppler

os.environ['DJANGO_SETTINGS_MODULE'] = 'gpapers.settings'
import gpapers.settings
import django.core.management
django.core.management.setup_environ(gpapers.settings)
from django.core.exceptions import MultipleObjectsReturned
from django.db.models import Q
from django.template import defaultfilters
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from gpapers.logger import *
from gpapers.importer import bibtex, pdf_file
import gpapers.desktop
from gpapers.gPapers.models import *
import gpapers.importer as importer
from gpapers.importer import pango_escape, get_md5_hexdigest_from_data
from gpapers.importer import pubmed, google_scholar, jstor

log_level_debug()

# our directory
BASE_DIR = os.path.abspath(os.path.split(__file__)[0])
PROGRAM = 'gPapers'
DATE_FORMAT = '%Y-%m-%d'
LEFT_PANE_ADD_TO_PLAYLIST_DND_ACTION = ('add_to_playlist',
                                        Gtk.TargetFlags.SAME_APP, 0)
MIDDLE_TOP_PANE_REORDER_PLAYLIST_DND_ACTION = ('reorder_playlist',
                                               Gtk.TargetFlags.SAME_WIDGET, 1)
PDF_PREVIEW_MOVE_NOTE_DND_ACTION = ('move_note', Gtk.TargetFlags.SAME_WIDGET,
                                    2)
NOTE_ICON = GdkPixbuf.Pixbuf.new_from_file(os.path.join(BASE_DIR, 'icons',
                                                        'note.png'))
BOOKMARK_ICON = GdkPixbuf.Pixbuf.new_from_file(os.path.join(BASE_DIR, 'icons',
                                                            'bookmark.png'))
GRAPH_ICON = GdkPixbuf.Pixbuf.new_from_file(os.path.join(BASE_DIR, 'icons',
                                                         'drawing.png'))

__version__ = '0.5dev'

GObject.threads_init()


def humanize_count(x, s, p, places=1):
    output = []
    if places == -1:
        places = 0
        print_x = False
    else:
        print_x = True
    x = float(x) * math.pow(10, places)
    x = round(x)
    x = x / math.pow(10, places)
    if x - int(x) == 0:
        x = int(x)
    if print_x: output.append(str(x))
    if x == 1:
        output.append(s)
    else:
        output.append(p)
    return ' '.join(output)


def truncate_long_str(s, max_length=96):
    s = str(s)
    if len(s) < max_length:
        return s
    else:
        return s[0:max_length] + '...'


def set_model_from_list(cb, items):
    """Setup a ComboBox or ComboBoxEntry based on a list of (int,str)s."""
    model = Gtk.ListStore(int, str)
    for i in items:
        model.append(i)
    cb.set_model(model)
    cell = Gtk.CellRendererText()
    cb.pack_start(cell, True)
    cb.add_attribute(cell, 'text', 1)


def index_of_in_list_of_lists(value, list, column, not_found= -1):
    for i in range(0, len(list)):
        if value == list[i][column]:
            return i
    return not_found


def make_all_columns_resizeable_clickable_ellipsize(columns):
    for column in columns:
        column.set_resizable(True)
        column.set_clickable(True)
        #column.connect('clicked', self.sortRows)
        for renderer in column.get_cells():
            if renderer.__class__.__name__ == 'CellRendererText':
                renderer.set_property('ellipsize', Pango.EllipsizeMode.END)


def fetch_citations_via_urls(urls):
    log_info('trying to fetch: %s' % str(urls))
    t = thread.start_new_thread(import_citations, (urls,))


def fetch_citations_via_references(references):
    log_info('trying to fetch: %s' % str(references))
    t = thread.start_new_thread(import_citations_via_references, (references,))


def import_citations(urls):
    for url in urls:
        importer.import_citation(url, callback=main_gui.refresh_middle_pane_search)
    main_gui.refresh_middle_pane_search()


def import_citations_via_references(references):
    for reference in references:
        if not reference.referenced_paper:
            if reference.url_from_referencing_paper:
                reference.referenced_paper = importer.import_citation(reference.url_from_referencing_paper)
                reference.save()
        if not reference.referencing_paper:
            if reference.url_from_referenced_paper:
                reference.referenced_paper = importer.import_citation(reference.url_from_referenced_paper)
                reference.save()
    main_gui.refresh_middle_pane_search()


def import_documents_via_filenames(filenames, callback):
    '''
    Adds existing files or directories to the database and copies the documents
    to the MEDIA_ROOT/papers directory.
    ``filenames`` is a sequence of filenames.
    '''

    log_info('Starting filename import for %d documents' % len(filenames))

    def get_all_files(basedir, filenames):
        '''
        Returns a flat list with all pdf files in the file/directory list
        '''
        results = []
        for filename in filenames:
            filename = os.path.join(basedir, filename)
            if os.path.isdir(filename):
                results.extend(get_all_files(filename, os.listdir(filename)))
            elif mimetypes.guess_type(filename)[0] == 'application/pdf':
                #TODO: Also allow other file types like ps.gz
                results.append(filename)
        return results

    all_files = get_all_files('', filenames)
    # TODO: Show an error message if no file is found?

    for filename in all_files:
        gfile = Gio.File.new_for_path(filename)
        # first argument is the `cancellable` object
        gfile.load_contents_async(None, callback, filename)

    main_gui.refresh_middle_pane_search()

def row_from_dictionary(info, provider=None):
    assert info is not None

    return (VirtualPaper(info, provider), )

def paper_from_dictionary(paper_info, paper=None):
    '''
    Adds all information from a `paper_info` dictionary to the given
    :class:`gPapers.model.Paper` object, creating and saving
    :class:`gPapers.model.Author` and :class:`gPapers.model.Source` objects
    if necessary.

    Returns the `paper` object.
    '''

    if paper is None:
        paper = Paper.objects.create()
    if paper_info is None:
        paper_info = {}

    # Journal
    if 'journal' in paper_info:
        #TODO: Volume etc
        if 'issue' in paper_info:
            source, created = Source.objects.get_or_create(name=paper_info['journal'],
                                                           issue=paper_info['issue'])
        else:
            source, created = Source.objects.get_or_create(name=paper_info['journal'])

        paper.source = source

        if 'year' in paper_info:
            paper.source.publication_date = date(int(paper_info['year']), 1, 1)

        paper.source.location = paper_info.get('location', '')
        paper.source.save()

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
    attributes = ['title', 'abstract', 'doi', 'extracted_text', 'bibtex']

    for attr in attributes:
        log_debug('Checking if %s is in paper_info' % attr)
        if attr in paper_info:
            log_debug('%s is in paper_info' % attr)
            paper.__setattr__(attr, paper_info[attr])

    paper.save()

    return paper


def render_paper_text_attribute(column, cell, model, iter, attribute):
    '''
    This function is used by the view of the list of papers to extract an 
    attribute from the paper object.
    '''
    paper = model.get_value(iter, 0)
    
    # special case some attributes that are not direct attributes of the paper object
    if attribute == 'Authors':
        authors = ', '.join([ author.name for author in paper.get_authors_in_order() ])
        cell.set_property('text', authors)
    elif attribute == 'Journal':
        if paper.source:
            journal = paper.source.name
        else:
            journal = ''
        cell.set_property('text', journal)
    elif attribute == 'Year':
        if paper.source and paper.source.publication_date:
            pub_year = str(paper.source.publication_date.year)
        else:
            pub_year = ''
        cell.set_property('text', pub_year)
    else:
        # Set the text to the value of the respective attribute
        cell.set_property('text', str(getattr(paper, attribute.lower())))


def render_paper_rating_attribute(column, cell, model, iter, data):
    '''
    This function is used by the view of the list of papers to extract the 
    rating from a paper object and pass it to the progress bar renderer used
    to display it
    '''
    paper = model.get_value(iter, 0)
    cell.value = paper.rating


def render_paper_document_attribute(column, cell, model, iter, widget):
    '''
    This function is used by the view of the list of papers to display a little
    icon for papers that have the text in the library.
    '''
    paper = model.get_value(iter, 0)

    if paper.full_text and os.path.isfile(paper.full_text.path):
        icon = widget.render_icon(Gtk.STOCK_DND, Gtk.IconSize.MENU)
    else:
        icon = None

    cell.set_property('pixbuf', icon)


class MainGUI:

    active_threads = {}

    def bibtex_received(self, bibtex_data, doi):
        '''
        Callback function that is called when new bibtex data for a paper
        arrives. Writes the information to the paper object and saves it.
        '''
        try:
            # Get the paper for the DOI -- should be only one!
            paper = Paper.objects.get(doi=doi)

            paper_info = bibtex.paper_info_from_bibtex(bibtex_data)
            paper_from_dictionary(paper_info, paper=paper)

        except django.MultipleObjectsReturned:
            log_warning('More than one paper in the database has DOI %s -- aborting.' % doi)
        except Paper.DoesNotExist:
            log_warning('No paper in the database has DOI %s -- aborting.' % doi)

    def document_imported(self, paper_info, paper_data, user_data):
        '''
        Should be called after a paper is imported. `paper_info` is a
        dictionary with document metadata, `paper_data` is the PDF itself.
        '''

        if user_data in importer.active_threads:
            del importer.active_threads[str(user_data)]

        if paper_data is None and paper_info is None:
            # FIXME: This should be handled via an error callback
            return

        if paper_data is not None:
            # Get some info from the PDF:
            paper_info_pdf = pdf_file.get_paper_info_from_pdf(paper_data)

            # Add everything that is not already known
            if paper_info is None:
                paper_info = paper_info_pdf
                # If we get a DOI, download the metadata
                need_paper_info = True
            else:
                need_paper_info = False
                for key in paper_info_pdf.keys():
                    if not key in paper_info:
                        paper_info[key] = paper_info_pdf[key]

            paper = paper_from_dictionary(paper_info)

            #TODO: What is a good filename? Make this configurable?
            if paper.doi:
                filename = 'doi_' + paper.doi
            elif paper.pubmed_id:
                filename = 'pubmed_' + paper.pubmed_id
            else:
                filename = 'internal_id_' + str(paper.id)

            filename = defaultfilters.slugify(filename) + '.pdf'
            log_debug('Saving paper to "%s"' % filename)
            paper.save_file(filename, paper_data)
            log_debug('Paper saved')
            if need_paper_info and paper.doi:
                log_debug('Downloading metadata')
                importer.get_bibtex_for_doi(paper.doi, self.bibtex_received)
        else:
            log_debug('Calling paper_from_dictionary for %s' % str(paper_info))
            paper = paper_from_dictionary(paper_info)

        paper.save()

    def import_url_dialog(self, o):
        '''
        Opens a dialog for entering an URL. For importing this URL,
        ``import_citation`` is called in a new thread.
        '''
        dialog = Gtk.MessageDialog(parent=self.main_window,
                                   type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   flags=Gtk.DialogFlags.MODAL)
        #dialog.connect('response', lambda x,y: dialog.destroy())
        dialog.set_markup('<b>Import URL...</b>\n\nEnter the URL you would like to import:')
        entry = Gtk.Entry()
        entry.set_activates_default(True)
        dialog.vbox.add(entry)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            url = entry.get_text()
            importer.active_threads[url] = 'Importing URL'
            importer.import_from_url(url, self.document_imported)

        dialog.destroy()

    def import_doi_dialog(self, o):
        '''
        Opens a dialog for entering a DOI. For importing this document from the
        http://dx.doi.org/... URL, ``import_citation`` is called in a new
        thread.
        '''
        dialog = Gtk.MessageDialog(parent=self.main_window,
                                   type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   flags=Gtk.DialogFlags.MODAL)
        #dialog.connect('response', lambda x,y: dialog.destroy())
        dialog.set_markup('<b>Import via DOI...</b>\n\nEnter the DOI name '
                          '(e.g., 10.1000/182) you would like to import:')
        entry = Gtk.Entry()
        entry.set_activates_default(True)
        dialog.vbox.add(entry)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            url = 'http://dx.doi.org/' + entry.get_text().strip()
            importer.active_threads[url] = 'Importing DOI'
            importer.import_from_url(url, self.document_imported)

        dialog.destroy()

    def import_file_dialog(self, o):
        '''
        Opens a dialog for chosing one or several files. If any files are 
        chosen, ``import_documents_via_filenames`` is called in a new thread.
        '''
        dialog = Gtk.FileChooserDialog(title='Select one or more files import…',
                                       parent=self.main_window,
                                       action=Gtk.FileChooserAction.OPEN,
                                       buttons=(Gtk.STOCK_CANCEL,
                                                Gtk.ResponseType.CANCEL,
                                                Gtk.STOCK_OPEN,
                                                Gtk.ResponseType.OK))
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_select_multiple(True)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:

            def mycallback(file_object, asyncresult, user_data):
                # Get the actual file content 
                file_content = file_object.load_contents_finish(asyncresult)[1]

                self.document_imported(paper_data=file_content, paper_info=None,
                                       user_data=user_data)

            import_documents_via_filenames(dialog.get_filenames(),
                                           mycallback)
        dialog.destroy()

    def import_directory_dialog(self, o):
        '''
        Opens a dialog for chosing a directory. If a directory is chosen,
        ``import_documents_via_filenames`` is called in a new thread.
        '''
        dialog = Gtk.FileChooserDialog(title='Select a directory to import…',
                                       parent=self.main_window,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER,
                                       buttons=(Gtk.STOCK_CANCEL,
                                                Gtk.ResponseType.CANCEL,
                                                Gtk.STOCK_OPEN,
                                                Gtk.ResponseType.OK))
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_select_multiple(True)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:

            def mycallback(file_object, asyncresult, user_data):
                # Get the actual file content 
                file_content = file_object.load_contents_finish(asyncresult)[1]

                self.document_imported(paper_data=file_content, paper_info=None,
                                       user_data=user_data)

            import_documents_via_filenames(dialog.get_filenames(),
                                           mycallback)
        dialog.destroy()

    def import_bibtex_dialog(self, o):
        '''
        Opens a dialog for entering/pasting BibTex information. For importing
        the information, ``import_documents_via_bibtexs`` is called in a new
        thread.
        '''
        dialog = Gtk.MessageDialog(parent=self.main_window,
                                   type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   flags=Gtk.DialogFlags.MODAL)
        #dialog.connect('response', lambda x,y: dialog.destroy())
        dialog.set_markup('<b>Import BibTex...</b>\n\nEnter the BibTex entry (or entries) you would like to import:')
        entry = Gtk.TextView()
        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.add(entry)
        scrolledwindow.set_property('height-request', 300)
        dialog.vbox.add(scrolledwindow)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:

            text_buffer = entry.get_buffer()
            bibtex_data = text_buffer.get_text(text_buffer.get_start_iter(),
                                          text_buffer.get_end_iter(), False)
            paper_info = bibtex.paper_info_from_bibtex(bibtex_data)

            url = paper_info.get('import_url')
            if not url:
                url = paper_info.get('doi')
                if url:
                    url = 'http://dx.doi.org/' + url

            if url:
                importer.import_from_url(url, self.document_imported,
                                         paper_info=paper_info)
            else:
                self.document_imported(paper_info, paper_data=None,
                                       user_data=None)

        dialog.destroy()

    def __init__(self):
        self.search_providers = {'pubmed' : pubmed.PubMedSearch(),
                         'google_scholar' : google_scholar.GoogleScholarSearch(),
                         'jstor' : jstor.JSTORSearch()}
        self.displayed_paper = None
        self.ui = Gtk.Builder()
        self.ui.add_from_file(os.path.join(BASE_DIR, 'data', 'ui.xml'))
        self.main_window = self.ui.get_object('main_window')
        self.main_window.connect("delete-event", lambda x, y: sys.exit(0))
        self.init_menu()
        # Save content of last search to avoid generating too many
        # search events
        self.last_middle_pane_search_string = ''
        self.last_middle_pane_performed_search = ''
        self.last_middle_pane_search_time = 0.0
        self.init_search_box()

        self.init_left_pane()
        self.init_my_library_filter_pane()
        self.init_middle_top_pane()
        self.init_paper_information_pane()
        self.init_busy_notifier()
        self.init_bookmark_pane()
        self.init_pdf_preview_pane()
        self.refresh_left_pane()

        # make sure the GUI updates on database changes
        def receiver_wrapper(sender, **kwargs):
            self.handle_library_updates()

        post_save.connect(receiver_wrapper, sender=Paper, weak=False)
        post_delete.connect(receiver_wrapper, sender=Paper, weak=False)

        self.main_window.show()

    def init_busy_notifier(self):
        busy_notifier = self.ui.get_object('busy_notifier')
        busy_notifier.set_from_file(os.path.join(BASE_DIR, 'icons', 'blank.gif'))
        self.busy_notifier_is_running = False

        treeview_running_tasks = self.ui.get_object('treeview_running_tasks')
        # thread_id, text
        self.treeview_running_tasks_model = Gtk.ListStore(str, str)
        treeview_running_tasks.set_model(self.treeview_running_tasks_model)

        renderer = Gtk.CellRendererText()
        renderer.set_property("background", "#fff7e8") # Gdk.color_parse("#fff7e8")
        column = Gtk.TreeViewColumn("Running Tasks...", renderer, text=1)
        column.set_expand(True)
        treeview_running_tasks.append_column(column)
        make_all_columns_resizeable_clickable_ellipsize(treeview_running_tasks.get_columns())

        GObject.timeout_add_seconds(1, self.watch_busy_notifier)

    def watch_busy_notifier(self):
        if len(self.active_threads):
            self.treeview_running_tasks_model.clear()
            for x in self.active_threads.items():
                self.treeview_running_tasks_model.append(x)
            if not self.busy_notifier_is_running:
                log_debug('Setting spinning busy notifier')
                self.ui.get_object('busy_notifier').set_from_file(os.path.join(BASE_DIR, 'icons', 'process-working.gif'))
                self.busy_notifier_is_running = True
                self.ui.get_object('treeview_running_tasks').show()
        else:
            if self.busy_notifier_is_running:
                self.ui.get_object('busy_notifier').set_from_file(os.path.join(BASE_DIR, 'icons', 'blank.gif'))
                self.busy_notifier_is_running = False
                self.ui.get_object('treeview_running_tasks').hide()

        # Assure that this function gets called again
        return True

    def init_menu(self):
        self.ui.get_object('menuitem_quit').connect('activate', lambda x: sys.exit(0))
        self.ui.get_object('menuitem_import_url').connect('activate', self.import_url_dialog)
        self.ui.get_object('menuitem_import_doi').connect('activate', self.import_doi_dialog)
        self.ui.get_object('menuitem_import_files').connect('activate', self.import_file_dialog)
        self.ui.get_object('menuitem_import_directory').connect('activate', self.import_directory_dialog)
        self.ui.get_object('menuitem_import_bibtex').connect('activate', self.import_bibtex_dialog)
        self.ui.get_object('menuitem_author_graph').connect('activate', lambda x: self.graph_authors())
        self.ui.get_object('menuitem_paper_graph').connect('activate', lambda x: self.graph_papers())
        self.ui.get_object('menuitem_about').connect('activate', self.show_about_dialog)

    def init_search_box(self):
        # Check the search box for changes every 0.25 seconds
        GObject.timeout_add(250, lambda x: self.middle_pane_search_changed(),
                            None)
        self.ui.get_object('refresh_middle_pane_search').connect('clicked', lambda x: self.refresh_middle_pane_search())
        self.ui.get_object('clear_middle_pane_search').connect('clicked', lambda x: self.clear_all_search_and_filters())
        self.ui.get_object('save_smart_search').connect('clicked', lambda x: self.save_smart_search())

    def show_about_dialog(self, o):
        about = Gtk.AboutDialog()
        about.set_program_name('gPapers')
        about.set_version(__version__)
        about.set_copyright('Copyright (c) 2008, 2009 Derek Anderson; 2012 Derek Anderson & Marcel Stimberg')
        about.set_comments('''The Gnome-based Scientific Paper Organizer''')
        about.set_license_type(Gtk.License.GPL_3_0)
        about.set_website('http://gpapers.org/')
        about.set_authors(['Derek Anderson <public@kered.org>',
                           'Marcel Stimberg'])
        about.connect('response', lambda x, y: about.destroy())
        about.show()

    def clear_all_search_and_filters(self):
        self.ui.get_object('middle_pane_search').set_text('')
        self.ui.get_object('author_filter').get_selection().unselect_all()
        self.ui.get_object('source_filter').get_selection().unselect_all()
        self.ui.get_object('organization_filter').get_selection().unselect_all()

    def save_smart_search(self):
        liststore, row = self.ui.get_object('left_pane_selection').get_selected()
        playlist, created = Playlist.objects.get_or_create(
            title='search: <i>%s</i>' % self.ui.get_object('middle_pane_search').get_text(),
            search_text=self.ui.get_object('middle_pane_search').get_text(),
            parent=self.search_providers[liststore[row][4]].label
        )
        if created: playlist.save()
        self.refresh_left_pane()

    def create_playlist(self, ids=None):
        playlist = Playlist.objects.create(
            title='<i>(new collection)</i>',
            parent='local'
        )
        if ids:
            for paper in Paper.objects.in_bulk(ids).values():
                playlist.papers.add(paper)
        playlist.save()
        self.refresh_left_pane()

    def refresh_middle_pane_search(self):
        selection = self.ui.get_object('left_pane_selection')
        liststore, row = selection.get_selected()
        if liststore[row][4] != 'local':
            # For the external search providers: clear cache
            text = self.ui.get_object('middle_pane_search').get_text()
            self.search_providers[liststore[row][4]].clear_cache(text)

        self.last_middle_pane_search_string = ''


    def middle_pane_search_changed(self):
        search_text = self.ui.get_object('middle_pane_search').get_text()
        # Only initiate a search if the string did not change since the last
        # check
        if search_text != self.last_middle_pane_search_string:
            log_debug('Search text changed, doing nothing')
            self.last_middle_pane_search_string = search_text
        else:
            self.last_middle_pane_search_string = search_text
            # The search text was stable and we did not search for this text yet
            if self.last_middle_pane_performed_search != search_text:
                log_debug('Search text changed, initiating search')
                self.last_middle_pane_performed_search = search_text
                self.select_left_pane_item(self.ui.get_object('left_pane_selection'))

        return True  # we do want repeated calls of the timeout

    def init_left_pane(self):
        '''
         Initializes the left pane, containing collections, playlists and 
         saved searches.
            
         The TreeStore consists of:
         name, icon, playlist_id, editable, source
         where:
         * `name` and `icon` are the visibly displayed name and icon
         * `playlist_id` is the id of the playlist in the database
         * `editable` is True only for Playlists (they can be renamed)
         * `source` is used for saved searches and the searches themselves
        '''
        left_pane = self.ui.get_object('left_pane')
        # name, icon, playlist_id, editable, source
        self.left_pane_model = Gtk.TreeStore(str, GdkPixbuf.Pixbuf, int, bool, str)
        left_pane.set_model(self.left_pane_model)

        column = Gtk.TreeViewColumn()
        left_pane.append_column(column)
        renderer = Gtk.CellRendererPixbuf()
        column.pack_start(renderer, False)
        column.add_attribute(renderer, 'pixbuf', 1)
        renderer = Gtk.CellRendererText()
        renderer.connect('edited', self.handle_playlist_edited)
        column.pack_start(renderer, True)
        column.add_attribute(renderer, 'markup', 0)
        column.add_attribute(renderer, 'editable', 3)

        self.ui.get_object('left_pane_selection').connect('changed', self.select_left_pane_item)
        left_pane.connect('button-press-event', self.handle_left_pane_button_press_event)

        left_pane.enable_model_drag_dest([LEFT_PANE_ADD_TO_PLAYLIST_DND_ACTION], Gdk.DragAction.COPY)
        left_pane.connect('drag-data-received', self.handle_left_pane_drag_data_received_event)
        left_pane.connect("drag-motion", self.handle_left_pane_drag_motion_event)

    def init_pdf_preview_pane(self):
        pdf_preview = self.ui.get_object('pdf_preview')
        self.pdf_preview = {}
        self.pdf_preview['scale'] = None
        pdf_preview.connect("draw", self.on_draw_pdf_preview)
        pdf_preview.connect("button-press-event", self.handle_pdf_preview_button_press_event)

        # drag and drop stuff for notes
        pdf_preview.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                                    [Gtk.TargetEntry.new(*PDF_PREVIEW_MOVE_NOTE_DND_ACTION)],
                                    Gdk.DragAction.MOVE)
        pdf_preview.drag_source_set_icon_pixbuf(NOTE_ICON)
        pdf_preview.drag_dest_set(Gtk.DestDefaults.ALL,
                                  [Gtk.TargetEntry.new(*PDF_PREVIEW_MOVE_NOTE_DND_ACTION)],
                                  Gdk.DragAction.MOVE)
        pdf_preview.connect('drag-drop', self.handle_pdf_preview_drag_drop_event)

        self.ui.get_object('button_move_previous_page').connect('clicked', lambda x: self.goto_pdf_page(self.pdf_preview['current_page_number'] - 1))
        self.ui.get_object('button_move_next_page').connect('clicked', lambda x: self.goto_pdf_page(self.pdf_preview['current_page_number'] + 1))
        self.ui.get_object('button_zoom_in').connect('clicked', lambda x: self.zoom_pdf_page(-1.2))
        self.ui.get_object('button_zoom_out').connect('clicked', lambda x: self.zoom_pdf_page(-.8))
        self.ui.get_object('button_zoom_normal').connect('clicked', lambda x: self.zoom_pdf_page(1))
        self.ui.get_object('button_zoom_best_fit').connect('clicked', lambda x: self.zoom_pdf_page(None))

    def refresh_pdf_preview_pane(self):
        pdf_preview = self.ui.get_object('pdf_preview')
        if self.displayed_paper and self.displayed_paper.full_text and os.path.isfile(self.displayed_paper.full_text.path):
            self.pdf_preview['document'] = Poppler.Document.new_from_file ('file://' + self.displayed_paper.full_text.path, None)
            self.pdf_preview['n_pages'] = self.pdf_preview['document'].get_n_pages()
            self.pdf_preview['scale'] = None
            self.goto_pdf_page(self.pdf_preview['current_page_number'], new_doc=True)
        else:
            pdf_preview.set_size_request(0, 0)
            self.pdf_preview['current_page'] = None
            self.ui.get_object('button_move_previous_page').set_sensitive(False)
            self.ui.get_object('button_move_next_page').set_sensitive(False)
            self.ui.get_object('button_zoom_out').set_sensitive(False)
            self.ui.get_object('button_zoom_in').set_sensitive(False)
            self.ui.get_object('button_zoom_normal').set_sensitive(False)
            self.ui.get_object('button_zoom_best_fit').set_sensitive(False)
        pdf_preview.queue_draw()

    def goto_pdf_page(self, page_number, new_doc=False):
        if self.displayed_paper:
            if not new_doc and self.pdf_preview.get('current_page') and self.pdf_preview['current_page_number'] == page_number:
                return
            if page_number < 0: page_number = 0
            pdf_preview = self.ui.get_object('pdf_preview')
            self.pdf_preview['current_page_number'] = page_number
            self.pdf_preview['current_page'] = self.pdf_preview['document'].get_page(self.pdf_preview['current_page_number'])
            if self.pdf_preview['current_page']:
                self.pdf_preview['width'], self.pdf_preview['height'] = self.pdf_preview['current_page'].get_size()
                self.ui.get_object('button_move_previous_page').set_sensitive(page_number > 0)
                self.ui.get_object('button_move_next_page').set_sensitive(page_number < self.pdf_preview['n_pages'] - 1)
                self.zoom_pdf_page(self.pdf_preview['scale'], redraw=False)
            else:
                self.ui.get_object('button_move_previous_page').set_sensitive(False)
                self.ui.get_object('button_move_next_page').set_sensitive(False)
            pdf_preview.queue_draw()
        else:
            self.ui.get_object('button_move_previous_page').set_sensitive(False)
            self.ui.get_object('button_move_next_page').set_sensitive(False)

    def zoom_pdf_page(self, scale, redraw=True):
        """None==auto-size, negative means relative, positive means fixed"""
        if self.displayed_paper:
            if redraw and self.pdf_preview.get('current_page') and self.pdf_preview['scale'] == scale:
                return
            pdf_preview = self.ui.get_object('pdf_preview')
            auto_scale = (pdf_preview.get_parent().get_allocation().width - 2.0) / self.pdf_preview['width']
            if scale == None:
                scale = auto_scale
            else:
                if scale < 0:
                    if self.pdf_preview['scale'] == None: self.pdf_preview['scale'] = auto_scale
                    scale = self.pdf_preview['scale'] = self.pdf_preview['scale'] * -scale
                else:
                    self.pdf_preview['scale'] = scale
            pdf_preview.set_size_request(int(self.pdf_preview['width'] * scale), int(self.pdf_preview['height'] * scale))
            self.ui.get_object('button_zoom_out').set_sensitive(scale > 0.3)
            self.ui.get_object('button_zoom_in').set_sensitive(True)
            self.ui.get_object('button_zoom_normal').set_sensitive(True)
            self.ui.get_object('button_zoom_best_fit').set_sensitive(True)
            if redraw: pdf_preview.queue_draw()
            return scale
        else:
            pass

    def on_draw_pdf_preview(self, widget, event):
        if not self.displayed_paper or not self.pdf_preview.get('current_page'): return
        cr = widget.get_window().cairo_create()
        cr.set_source_rgb(1, 1, 1)
        scale = self.pdf_preview['scale']
        if scale == None:
            scale = (self.ui.get_object('pdf_preview').get_parent().get_allocation().width - 2.0) / self.pdf_preview['width']
        if scale != 1:
            cr.scale(scale, scale)
        cr.rectangle(0, 0, self.pdf_preview['width'], self.pdf_preview['height'])
        cr.fill()
        self.pdf_preview['current_page'].render(cr)
        if self.pdf_preview.get('current_page_number') != None:
            for bookmark in Bookmark.objects.filter(paper=self.displayed_paper, page=self.pdf_preview.get('current_page_number')):
                x_pos = int(bookmark.x * widget.get_allocated_width())
                y_pos = int(bookmark.y * widget.get_allocated_height())
                if bookmark.notes:
                    Gdk.cairo_set_source_pixbuf(cr, NOTE_ICON, x_pos, y_pos)
                else:
                    Gdk.cairo_set_source_pixbuf(cr, BOOKMARK_ICON, x_pos, y_pos)
                cr.paint()


    def init_my_library_filter_pane(self):

        author_filter = self.ui.get_object('author_filter')
        # id, author, paper_count
        self.author_filter_model = Gtk.ListStore(int, str, int)
        author_filter.set_model(self.author_filter_model)
        author_filter.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        column = Gtk.TreeViewColumn("Author", Gtk.CellRendererText(), text=1)
        column.set_sort_column_id(1)
        column.set_expand(True)
        author_filter.append_column(column)
        column = Gtk.TreeViewColumn("Papers", Gtk.CellRendererText(), text=2)
        column.set_sort_column_id(2)
        author_filter.append_column(column)
        make_all_columns_resizeable_clickable_ellipsize(author_filter.get_columns())
        author_filter.get_selection().connect('changed', lambda x: thread.start_new_thread(self.refresh_middle_pane_from_my_library, (False,)))
        author_filter.connect('row-activated', self.handle_author_filter_row_activated)
        author_filter.connect('button-press-event', self.handle_author_filter_button_press_event)

        organization_filter = self.ui.get_object('organization_filter')
        # id, org, author_count, paper_count
        self.organization_filter_model = Gtk.ListStore(int, str, int, int)
        organization_filter.set_model(self.organization_filter_model)
        organization_filter.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        column = Gtk.TreeViewColumn("Organization", Gtk.CellRendererText(), text=1)
        column.set_sort_column_id(1)
        column.set_expand(True)
        organization_filter.append_column(column)
        column = Gtk.TreeViewColumn("Authors", Gtk.CellRendererText(), text=2)
        column.set_sort_column_id(2)
        organization_filter.append_column(column)
        column = Gtk.TreeViewColumn("Papers", Gtk.CellRendererText(), text=3)
        column.set_sort_column_id(3)
        organization_filter.append_column(column)
        make_all_columns_resizeable_clickable_ellipsize(organization_filter.get_columns())
        organization_filter.get_selection().connect('changed', lambda x: thread.start_new_thread(self.refresh_middle_pane_from_my_library, (False,)))
        organization_filter.connect('row-activated', self.handle_organization_filter_row_activated)
        organization_filter.connect('button-press-event', self.handle_organization_filter_button_press_event)

        source_filter = self.ui.get_object('source_filter')
        # id, name, issue, location, publisher, date
        self.source_filter_model = Gtk.ListStore(int, str, str, str, str, str)
        source_filter.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        source_filter.set_model(self.source_filter_model)
        column = Gtk.TreeViewColumn("Source", Gtk.CellRendererText(), text=1)
        column.set_sort_column_id(1)
        column.set_expand(True)
        source_filter.append_column(column)
        column = Gtk.TreeViewColumn("Issue", Gtk.CellRendererText(), text=2)
        column.set_sort_column_id(2)
        source_filter.append_column(column)
        column = Gtk.TreeViewColumn("Location", Gtk.CellRendererText(), text=3)
        column.set_sort_column_id(3)
        source_filter.append_column(column)
        column = Gtk.TreeViewColumn("Publisher", Gtk.CellRendererText(), text=4)
        column.set_sort_column_id(4)
        source_filter.append_column(column)
        make_all_columns_resizeable_clickable_ellipsize(source_filter.get_columns())
        source_filter.get_selection().connect('changed', lambda x: thread.start_new_thread(self.refresh_middle_pane_from_my_library, (False,)))
        source_filter.connect('row-activated', self.handle_source_filter_row_activated)
        source_filter.connect('button-press-event', self.handle_source_filter_button_press_event)

    def refresh_my_library_filter_pane(self):

        self.author_filter_model.clear()
        for author in Author.objects.order_by('name'):
            self.author_filter_model.append((author.id, author.name, author.paper_set.count()))

        self.organization_filter_model.clear()
        for organization in Organization.objects.order_by('name'):
            self.organization_filter_model.append((organization.id, organization.name, organization.author_set.count(), organization.paper_set.count()))

        self.source_filter_model.clear()
        for source in Source.objects.order_by('name'):
            if source.publication_date:
                publication_date = source.publication_date.strftime('%Y-%m-%d')
            else:
                publication_date = ''
            self.source_filter_model.append((source.id, source.name,
                                             source.issue, source.location,
                                             source.publisher,
                                             publication_date))


    def init_bookmark_pane(self):
        treeview_bookmarks = self.ui.get_object('treeview_bookmarks')
        # id, page, title, updated, words
        self.treeview_bookmarks_model = Gtk.ListStore(int, int, str, str, int)
        treeview_bookmarks.set_model(self.treeview_bookmarks_model)
        column = Gtk.TreeViewColumn("Page", Gtk.CellRendererText(), markup=1)
        column.set_sort_column_id(1)
        treeview_bookmarks.append_column(column)
        column = Gtk.TreeViewColumn("Title", Gtk.CellRendererText(), markup=2)
        column.set_expand(True)
        column.set_sort_column_id(2)
        treeview_bookmarks.append_column(column)
        column = Gtk.TreeViewColumn("Words", Gtk.CellRendererText(), markup=4)
        column.set_sort_column_id(4)
        treeview_bookmarks.append_column(column)
        column = Gtk.TreeViewColumn("Updated", Gtk.CellRendererText(), markup=3)
        column.set_min_width(75)
        column.set_sort_column_id(3)
        treeview_bookmarks.append_column(column)
        make_all_columns_resizeable_clickable_ellipsize(treeview_bookmarks.get_columns())
        treeview_bookmarks.connect('button-press-event', self.handle_treeview_bookmarks_button_press_event)

        treeview_bookmarks.get_selection().connect('changed', self.select_bookmark_pane_item)

    def save_bookmark_page(self, bookmark_id, page):
        bookmark = Bookmark.objects.get(id=bookmark_id)
        bookmark.page = page
        bookmark.save()

    def init_paper_information_pane(self):
        paper_notes = self.ui.get_object('paper_notes')
        paper_notes.modify_base(Gtk.StateType.NORMAL, Gdk.color_parse("#fff7e8"))
        paper_notes.modify_base(Gtk.StateType.INSENSITIVE, Gdk.color_parse("#ffffff"))
        pane = self.ui.get_object('paper_information_pane')
        # text
        self.paper_information_pane_model = Gtk.ListStore(str, str)
        pane.set_model(self.paper_information_pane_model)

        pane.connect('size-allocate', self.resize_paper_information_pane)

        column = Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=0)
        column.set_min_width(64)
        pane.append_column(column)

        column = Gtk.TreeViewColumn()
        renderer = Gtk.CellRendererText()
        #renderer.set_property('editable', True)
        renderer.set_property('wrap-mode', Pango.WrapMode.WORD)
        renderer.set_property('wrap-width', 500)
        column.pack_start(renderer, True)
        column.add_attribute(renderer, 'markup', 1)
        pane.append_column(column)

    def resize_paper_information_pane(self, treeview, o2, width=None):
        if width == None:
            width = treeview.get_column(1).get_width() - 16
        treeview.get_column(1).get_cells()[0].set_property('wrap-width', width)

    def handle_library_updates(self):
        log_debug('handle_libray_updates called')
        selection = self.ui.get_object('left_pane_selection')
        liststore, row = selection.get_selected()
        if liststore[row][4] == 'local':
            # Re-select to force a refresh            
            self.refresh_my_library_count()
            self.select_left_pane_item(self.ui.get_object('left_pane_selection'))

    def refresh_left_pane(self):
        # FIXME: These should not be loaded again and again
        NEVER_READ_ICON = GdkPixbuf.Pixbuf.new_from_file(os.path.join(BASE_DIR,
                                                                      'icons',
                                                                      'applications-development.png'))
        FAVORITE_ICON = GdkPixbuf.Pixbuf.new_from_file(os.path.join(BASE_DIR,
                                                                    'icons',
                                                                    'emblem-favorite.png'))
        left_pane = self.ui.get_object('left_pane')
        self.left_pane_model.clear()
        self.left_pane_model.append(None, ('<b>My Library</b>',
                                           left_pane.render_icon(Gtk.STOCK_HOME,
                                                                 Gtk.IconSize.MENU),
                                           - 1, False, 'local'))
        for playlist in Playlist.objects.filter(parent='local'):
            if playlist.search_text:
                icon = left_pane.render_icon(Gtk.STOCK_FIND, Gtk.IconSize.MENU)
            else:
                icon = left_pane.render_icon(Gtk.STOCK_DND_MULTIPLE, Gtk.IconSize.MENU)
            self.left_pane_model.append(self.left_pane_model.get_iter((0),),
                                        (playlist.title, icon, playlist.id,
                                         True, 'local'))
        self.left_pane_model.append(self.left_pane_model.get_iter((0),),
                                    ('<i>recently added</i>',
                                     left_pane.render_icon(Gtk.STOCK_NEW,
                                                           Gtk.IconSize.MENU),
                                     - 2, False, 'local'))
        self.left_pane_model.append(self.left_pane_model.get_iter((0),),
                                    ('<i>most often read</i>',
                                     left_pane.render_icon(Gtk.STOCK_DIALOG_INFO,
                                                           Gtk.IconSize.MENU),
                                     - 3, False, 'local'))
        self.left_pane_model.append(self.left_pane_model.get_iter((0),),
                                    ('<i>never read</i>',
                                     NEVER_READ_ICON, -5, False, 'local'))
        self.left_pane_model.append(self.left_pane_model.get_iter((0),),
                                    ('<i>highest rated</i>',
                                     FAVORITE_ICON, -4, False, 'local'))

        for _, provider in self.search_providers.iteritems():
            # FIXME: Load them in the providers
            provider_icon = GdkPixbuf.Pixbuf.new_from_file(os.path.join(BASE_DIR,
                                                                        'icons',
                                                                        provider.icon))
            self.left_pane_model.append(None, (provider.name,
                             provider_icon, -1, False, provider.label))
            for playlist in Playlist.objects.filter(parent=provider.label):
                print 'paylist item', playlist
                icon = left_pane.render_icon(Gtk.STOCK_FIND, Gtk.IconSize.MENU)
                self.left_pane_model.append(self.left_pane_model.get_iter((1),),
                                            (playlist.title, icon, playlist.id,
                                             True, provider.label))

        left_pane.expand_all()
        self.ui.get_object('left_pane_selection').select_path((0,))

    def select_left_pane_item(self, selection):
        liststore, row = selection.get_selected()
        left_pane_toolbar = self.ui.get_object('left_pane_toolbar')
        for child in left_pane_toolbar.get_children():
            left_pane_toolbar.remove(child)
        if not row:
            self.ui.get_object('middle_pane_label').set_markup('<i>nothing selected</i>')
            return
        self.ui.get_object('middle_pane_label').set_markup(liststore[row][0])
        self.middle_top_pane_model.clear()

        button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
        button.set_tooltip_text('Create a new document collection...')
        button.connect('clicked', lambda x: self.create_playlist())
        button.show()
        left_pane_toolbar.insert(button, -1)

        try:
            self.current_playlist = Playlist.objects.get(id=liststore[row][2])
            button = Gtk.ToolButton(stock_id=Gtk.STOCK_DELETE)
            button.set_tooltip_text('Delete this collection...')
            button.connect('clicked', lambda x: self.delete_playlist(self.current_playlist.id))
            button.show()
            left_pane_toolbar.insert(button, -1)
        except: self.current_playlist = None

        if liststore[row][2] == -2:
            self.current_papers = Paper.objects.filter(created__gte=datetime.now() - timedelta(7)).order_by('-created')[:20]
        elif liststore[row][2] == -3:
            self.current_papers = Paper.objects.filter(read_count__gte=1).order_by('-read_count')[:20]
        elif liststore[row][2] == -4:
            self.current_papers = Paper.objects.filter(rating__gte=1).order_by('-rating')[:20]
        elif liststore[row][2] == -5:
            self.current_papers = Paper.objects.filter(read_count=0)
        else:
            self.current_papers = None

        if self.current_playlist:
            if self.current_playlist.search_text:
                self.last_middle_pane_search_string = self.current_playlist.search_text
                self.ui.get_object('middle_pane_search').set_text(self.current_playlist.search_text)
            else:
                self.last_middle_pane_search_string = ''
                self.ui.get_object('middle_pane_search').set_text('')
#            if len(self.current_playlist.papers.count()):

        if self.current_papers != None:
            self.last_middle_pane_search_string = ''
            self.ui.get_object('middle_pane_search').set_text('')

        if liststore[row][4] == 'local':
            self.refresh_middle_pane_from_my_library(True)
        else:
            def error_callback(data1, data2):
                print 'Error callback, received data1: ', data1
                print 'Error callback, received data2: ', data2

            self.search_providers[liststore[row][4]].search(self.ui.get_object('middle_pane_search').get_text(),
                                                            self.refresh_middle_pane_from_external, error_callback)

        self.select_middle_top_pane_item(self.ui.get_object('middle_top_pane').get_selection())

    def init_middle_top_pane(self):
        middle_top_pane = self.ui.get_object('middle_top_pane')
        # We directly save Paper objects in the model
        # TODO: Column sorting no longer works...
        self.middle_top_pane_model = Gtk.ListStore(object)
        middle_top_pane.set_model(self.middle_top_pane_model)
        middle_top_pane.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        middle_top_pane.connect('button-press-event',
                                self.handle_middle_top_pane_button_press_event)

        column = Gtk.TreeViewColumn()
        column.set_title('Title')
        column.set_expand(True)
        renderer = Gtk.CellRendererPixbuf()
        column.set_cell_data_func(renderer, render_paper_document_attribute,
                                  middle_top_pane)
        column.pack_start(renderer, False)
        renderer = Gtk.CellRendererText()
        column.pack_start(renderer, True)
        column.set_cell_data_func(renderer, render_paper_text_attribute, 
                                  'Title')
                  
        middle_top_pane.append_column(column)
        for attribute in ['Authors', 'Journal', 'Year', 'Created']:
            column = Gtk.TreeViewColumn(attribute)            
            renderer = Gtk.CellRendererText()
            column.pack_start(renderer, True)
            column.set_cell_data_func(renderer, render_paper_text_attribute,
                                      attribute)
            if attribute == 'Authors':
                # only authors and title column should expand
                column.set_expand(True)
            middle_top_pane.append_column(column)

        make_all_columns_resizeable_clickable_ellipsize(middle_top_pane.get_columns())

        middle_top_pane.connect('row-activated', self.handle_middle_top_pane_row_activated)
        middle_top_pane.get_selection().connect('changed', self.select_middle_top_pane_item)

        middle_top_pane.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, [LEFT_PANE_ADD_TO_PLAYLIST_DND_ACTION, MIDDLE_TOP_PANE_REORDER_PLAYLIST_DND_ACTION], Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        middle_top_pane.connect('drag-data-get', self.handle_middle_top_pane_drag_data_get)
        middle_top_pane.enable_model_drag_dest([MIDDLE_TOP_PANE_REORDER_PLAYLIST_DND_ACTION], Gdk.DragAction.MOVE)
        middle_top_pane.connect('drag-data-received', self.handle_middle_top_pane_drag_data_received_event)

    def handle_middle_top_pane_row_activated(self, treeview, path, view_column):
        liststore, rows = treeview.get_selection().get_selected()
        paper = treeview.get_model().get_value(treeview.get_model().get_iter(path), 0)
        try:
            paper.open()
        except:
            traceback.print_exc()

    def handle_middle_top_pane_drag_data_get(self, treeview, context, selection, info, timestamp):
        liststore, row = treeview.get_selection().get_selected()
        id = liststore[row][0]
        selection.set('text/plain', len(str(id)), str(id))

    def handle_author_filter_row_activated(self, treeview, path, view_column):
        liststore, rows = treeview.get_selection().get_selected()
        id = treeview.get_model().get_value(treeview.get_model().get_iter(path), 0)
        AuthorEditGUI(id)

    def handle_organization_filter_row_activated(self, treeview, path, view_column):
        liststore, rows = treeview.get_selection().get_selected()
        id = treeview.get_model().get_value(treeview.get_model().get_iter(path), 0)
        OrganizationEditGUI(id)

    def handle_source_filter_row_activated(self, treeview, path, view_column):
        liststore, rows = treeview.get_selection().get_selected()
        id = treeview.get_model().get_value(treeview.get_model().get_iter(path), 0)
        SourceEditGUI(id)

    def handle_left_pane_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                playlist_id = self.left_pane_model.get_value(self.left_pane_model.get_iter(path), 2)
                if playlist_id >= 0: #len(path)==2:
                    menu = Gtk.Menu()
                    delete = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_DELETE, None)
                    delete.connect('activate', lambda x: self.delete_playlist(playlist_id))
                    menu.append(delete)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_pdf_preview_button_press_event(self, pdf_preview, event):
        x = int(event.x)
        y = int(event.y)
        x_percent = 1.0 * x / pdf_preview.get_allocated_width()
        y_percent = 1.0 * y / pdf_preview.get_allocated_height()
        time = event.time
        #print 'x, y, x_percent, y_percent, time', x, y, x_percent, y_percent, time

        # are we clicking on a bookmark?
        current_page_number = self.pdf_preview.get('current_page_number')
        self.current_bookmark = bookmark = None
        if self.displayed_paper and current_page_number >= 0:
            for b in self.displayed_paper.bookmark_set.filter(paper=self.displayed_paper, page=current_page_number):
                x_delta = x - b.x * pdf_preview.get_allocated_width()
                y_delta = y - b.y * pdf_preview.get_allocated_height()
                if x_delta > 0 and x_delta < 16:
                    if y_delta > 0 and y_delta < 16:
                        self.current_bookmark = bookmark = b

        if event.button == 1 and bookmark:
            self.select_bookmark_pane_item(None, bookmark_id=bookmark.id)
            if bookmark.notes:
                pdf_preview.drag_source_set_icon_pixbuf(NOTE_ICON)
            else:
                pdf_preview.drag_source_set_icon_pixbuf(BOOKMARK_ICON)

        if event.button == 3:
            if self.displayed_paper and current_page_number >= 0:
                menu = Gtk.Menu()
                if bookmark:
                    if bookmark.page > 0:
                        menuitem = Gtk.MenuItem('Move to previous page')
                        menuitem.connect('activate', lambda x, i: self.move_bookmark(bookmark, page=i), bookmark.page - 1)
                        menu.append(menuitem)
                    if bookmark.page < self.pdf_preview['n_pages'] - 1:
                        menuitem = Gtk.MenuItem('Move to next page')
                        menuitem.connect('activate', lambda x, i: self.move_bookmark(bookmark, page=i), bookmark.page + 1)
                        menu.append(menuitem)
                    if self.pdf_preview['n_pages'] > 1:
                        menuitem = Gtk.MenuItem('Move to page')
                        submenu = Gtk.Menu()
                        for i in range(0, self.pdf_preview['n_pages']):
                            submenu_item = Gtk.MenuItem(str(i + 1))
                            submenu_item.connect('activate', lambda x, i: self.move_bookmark(bookmark, i), i)
                            submenu.append(submenu_item)
                        menuitem.set_submenu(submenu)
                        menu.append(menuitem)
                    delete = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_DELETE, None)
                    delete.connect('activate', lambda x: self.delete_bookmark(bookmark.id))
                    menu.append(delete)
                else:
                    add = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_ADD, None)
                    add.connect('activate', lambda x: self.add_bookmark(self.displayed_paper, current_page_number, x_percent, y_percent))
                    menu.append(add)
                menu.show_all()
                menu.attach_to_widget(pdf_preview, None)
                menu.popup(None, None, None, None, event.button, event.get_time())

        return bookmark == None # return true if bookmark not defined, to block DND events

    def handle_pdf_preview_drag_drop_event(self, o1, o2, x, y, o3):
        if self.current_bookmark:
            pdf_preview = self.ui.get_object('pdf_preview')
            x_percent = 1.0 * x / pdf_preview.get_allocated_width()
            y_percent = 1.0 * y / pdf_preview.get_allocated_height()
            self.current_bookmark.x = x_percent
            self.current_bookmark.y = y_percent
            self.current_bookmark.save()

    def add_bookmark(self, paper, page, x, y):
        bookmark = Bookmark.objects.create(paper=paper, page=page, x=x, y=y)
        bookmark.save()
        self.update_bookmark_pane_from_paper(self.displayed_paper)
        self.select_bookmark_pane_item(None, bookmark_id=bookmark.id)

    def move_bookmark(self, bookmark, page=None, x=None, y=None):
        if bookmark:
            if page != None:
                bookmark.page = page
            if x != None:
                bookmark.x = x
            if y != None:
                bookmark.y = y
            bookmark.save()
            self.update_bookmark_pane_from_paper(self.displayed_paper)

    def handle_middle_top_pane_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                paper = self.middle_top_pane_model.get_value(self.middle_top_pane_model.get_iter(path), 0)
                menu = Gtk.Menu()
                if paper and paper.full_text and os.path.isfile(paper.full_text.path):
                    button = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_OPEN, None)
                    button.connect('activate', lambda x: paper.open())
                    menu.append(button)
                button = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_EDIT, None)
                button.connect('activate', lambda x: PaperEditGUI(paper.id))
                menu.append(button)
                button = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_DELETE, None)
                button.connect('activate', lambda x: self.delete_papers([paper.id]))
                menu.append(button)
                menu.show_all()
                menu.attach_to_widget(treeview, None)
                menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_author_filter_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.author_filter_model.get_value(self.author_filter_model.get_iter(path), 0)
                if id >= 0: #len(path)==2:
                    menu = Gtk.Menu()
                    edit = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_EDIT, None)
                    edit.connect('activate', lambda x: AuthorEditGUI(id))
                    menu.append(edit)
                    edit = Gtk.MenuItem('Colleague Graph...')
                    edit.connect('activate', lambda x: self.graph_authors([id]))
                    menu.append(edit)

                    menuitem = Gtk.MenuItem('Connect to...')
                    submenu = Gtk.Menu()
                    for author in Author.objects.order_by('name'):
                        if author.id != id:
                            menu_item = Gtk.MenuItem(truncate_long_str(author.name))
                            menu_item.connect('activate', lambda x, author, id: AuthorEditGUI(id).connect(author, id), author, id)
                            submenu.append(menu_item)
                    menuitem.set_submenu(submenu)
                    menu.append(menuitem)

                    delete = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_DELETE, None)
                    delete.connect('activate', lambda x: self.delete_author(id))
                    menu.append(delete)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_source_filter_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.source_filter_model.get_value(self.source_filter_model.get_iter(path), 0)
                if id >= 0: #len(path)==2:
                    menu = Gtk.Menu()
                    edit = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_EDIT, None)
                    edit.connect('activate', lambda x: SourceEditGUI(id))
                    menu.append(edit)
                    delete = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_DELETE, None)
                    delete.connect('activate', lambda x: self.delete_source(id))
                    menu.append(delete)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_treeview_bookmarks_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.treeview_bookmarks_model.get_value(self.treeview_bookmarks_model.get_iter(path), 0)
                if id >= 0: #len(path)==2:
                    menu = Gtk.Menu()
                    delete = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_DELETE, None)
                    delete.connect('activate', lambda x: self.delete_bookmark(id))
                    menu.append(delete)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_organization_filter_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.organization_filter_model.get_value(self.organization_filter_model.get_iter(path), 0)
                if id >= 0: #len(path)==2:
                    menu = Gtk.Menu()
                    edit = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_EDIT, None)
                    edit.connect('activate', lambda x: OrganizationEditGUI(id))
                    menu.append(edit)
                    delete = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_DELETE, None)
                    delete.connect('activate', lambda x: self.delete_organization(id))
                    menu.append(delete)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_left_pane_drag_data_received_event(self, treeview, context, x, y, selection, info, timestamp):
        try:
            drop_info = treeview.get_dest_row_at_pos(x, y)
            if drop_info:
                model = treeview.get_model()
                path, position = drop_info
                data = selection.data
                playlist = Playlist.objects.get(id=model.get_value(model.get_iter(path), 2))
                playlist.papers.add(Paper.objects.get(id=int(data)))
                playlist.save()
            return
        except:
            traceback.print_exc()

    def handle_middle_top_pane_drag_data_received_event(self, treeview, context, x, y, selection, info, timestamp):
        try:
            drop_info = treeview.get_dest_row_at_pos(x, y)
            if drop_info and self.current_playlist:
                model = treeview.get_model()
                path, position = drop_info
                data = selection.data
                playlist = self.current_playlist
                paper_list = list(playlist.papers.all())
                l = []
                for i in range(0, len(paper_list)):
                    paper = paper_list[i]
                    if str(paper.id) == str(data):
                        break
                if path[0] == i:
                    return
                if path[0] == i + 1 and (position == Gtk.TreeViewDropPosition.AFTER or position == Gtk.TreeViewDropPosition.INTO_OR_AFTER):
                    return
                if path[0] == i - 1 and (position == Gtk.TreeViewDropPosition.BEFORE or position == Gtk.TreeViewDropPosition.INTO_OR_BEFORE):
                    return
                paper_list[i] = None
                if position == Gtk.TreeViewDropPosition.BEFORE or position == Gtk.TreeViewDropPosition.INTO_OR_BEFORE:
                    paper_list.insert(path[0], paper)
                if position == Gtk.TreeViewDropPosition.AFTER or position == Gtk.TreeViewDropPosition.INTO_OR_AFTER:
                    paper_list.insert(path[0] + 1, paper)
                paper_list.remove(None)
                playlist.papers.clear()
                for paper in paper_list:
                    playlist.papers.add(paper)
                thread.start_new_thread(self.refresh_middle_pane_from_my_library, (False,))
            if not self.current_playlist:
                log_info('can only reorder playlists')
        except:
            traceback.print_exc()

    def handle_left_pane_drag_motion_event(self, treeview, drag_context, x, y, eventtime):
        try:
            target_path, drop_position = treeview.get_dest_row_at_pos(x, y)
            model, source = treeview.get_selection().get_selected()
            target = model.get_iter(target_path)
            if len(target_path) > 1 and target_path[0] == 0:
                treeview.enable_model_drag_dest([LEFT_PANE_ADD_TO_PLAYLIST_DND_ACTION], Gdk.DragAction.MOVE)
            else:
                treeview.enable_model_drag_dest([], Gdk.DragAction.MOVE)
        except:
            # this will occur when we're not over a target
            # traceback.print_exc()
            treeview.enable_model_drag_dest([], Gdk.DragAction.MOVE)

    def handle_playlist_edited(self, renderer, path, new_text):
        playlist_id = self.left_pane_model.get_value(self.left_pane_model.get_iter_from_string(path), 2)
        playlist = Playlist.objects.get(id=playlist_id)
        playlist.title = new_text
        playlist.save()
        self.refresh_left_pane()

    def import_citation_via_middle_top_pane_row(self, row):
        paper_obj = row[0]
        importer.get_or_create_paper_via(paper_obj, callback=self.document_imported)

    def select_middle_top_pane_item(self, selection):
        liststore, rows = selection.get_selected_rows()
        self.paper_information_pane_model.clear()
        self.ui.get_object('paper_information_pane').columns_autosize()
        paper_information_toolbar = self.ui.get_object('paper_information_toolbar')
        for child in paper_information_toolbar.get_children():
            paper_information_toolbar.remove(child)
        self.displayed_paper = None

        log_debug('rows: %s' % str(rows))

        if not rows or len(rows) == 0:
            self.update_bookmark_pane_from_paper(None)
        elif len(rows) == 1:
            # a single selected paper
            self.displayed_paper = paper = liststore[rows[0]][0]
            if paper.title:
                self.paper_information_pane_model.append(('<b>Title:</b>',
                                                          paper.title ,))
            if liststore[rows[0]][0].authors:
                author_str = ', '.join([ author.name for author in
                                        paper.get_authors_in_order() ])
                self.paper_information_pane_model.append(('<b>Authors:</b>',
                                                          author_str,))
#            if liststore[rows[0]][3]:
#                self.paper_information_pane_model.append(('<b>Journal:</b>', liststore[rows[0]][3] ,))
            if paper.doi:
                self.paper_information_pane_model.append(('<b>DOI:</b>',
                                                          pango_escape(paper.doi) ,))
            if paper.pubmed_id:
                self.paper_information_pane_model.append(('<b>PubMed:</b>',
                                                          pango_escape(paper.pubmed_id) ,))
            if paper.import_url:
                self.paper_information_pane_model.append(('<b>Import URL:</b>',
                                                          pango_escape(paper.import_url) ,))
            status = []
            if paper and paper.full_text and os.path.isfile(paper.full_text.path):
                status.append('Full text saved in local library.')
                button = Gtk.ToolButton(stock_id=Gtk.STOCK_OPEN)
                button.set_tooltip_text('Open the full text of this paper in a new window...')
                button.connect('clicked', lambda x: paper.open())
                paper_information_toolbar.insert(button, -1)
            if status:
                self.paper_information_pane_model.append(('<b>Status:</b>', pango_escape('\n'.join(status)) ,))
#            if paper.source:
#                description.append( 'Source:  %s %s (pages: %s)' % ( str(paper.source), paper.source_session, paper.source_pages ) )
            if paper.abstract:
                self.paper_information_pane_model.append(('<b>Abstract:</b>',
                                                          pango_escape(paper.abstract) ,))
#            description.append( '' )
#            description.append( 'References:' )
#            for ref in paper.reference_set.all():
#                description.append( ref.line )
            #self.ui.get_object('paper_information_pane').get_buffer().set_text( '\n'.join(description) )            

            if paper.doi or paper.import_url:
                log_debug('URL or DOI exists')
                button = Gtk.ToolButton(stock_id=Gtk.STOCK_HOME)
                button.set_tooltip_text('Open this URL in your browser...')
                url = paper.import_url
                if not url:
                    url = 'http://dx.doi.org/' + paper.doi
                button.connect('clicked', lambda x: desktop.open(url))
                paper_information_toolbar.insert(button, -1)
                if paper.id != -1:
                    button = Gtk.ToolButton(stock_id=Gtk.STOCK_REFRESH)
                    button.set_tooltip_text('Re-add this paper to your library...')
                    
                    button.connect('clicked', lambda x: self.import_citation_via_middle_top_pane_row(liststore[rows[0]]))
                    paper_information_toolbar.insert(button, -1)

            if paper.id == -1 and hasattr(paper, 'provider'):  # This is a search result
                button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
                button.set_tooltip_text('Add this paper to your library...')
                button.connect('clicked',
                               lambda x: paper.provider.import_paper_after_search(paper.data,
                                                                                  self.document_imported))
                paper_information_toolbar.insert(button, -1)
            elif paper.id != -1:
                importable_references = set()
                references = paper.reference_set.order_by('id')
#                self.paper_information_pane_model.append(( '<b>References:</b>', '\n'.join( [ '<i>'+ str(i) +':</i> '+ references[i].line_from_referencing_paper for i in range(0,len(references)) ] ) ,))
                for i in range(0, len(references)):
                    if i == 0: col1 = '<b>References:</b>'
                    else: col1 = ''
                    if references[i].url_from_referencing_paper and not references[i].referenced_paper:
                        importable_references.add(references[i])
                    self.paper_information_pane_model.append((col1, '<i>' + str(i + 1) + ':</i> ' + pango_escape(references[i].line_from_referencing_paper)))
                importable_citations = set()
                citations = paper.citation_set.order_by('id')
#                self.paper_information_pane_model.append(( '<b>Citations:</b>', '\n'.join( [ '<i>'+ str(i) +':</i> '+ citations[i].line_from_referenced_paper for i in range(0,len(citations)) ] ) ,))
                for i in range(0, len(citations)):
                    if i == 0: col1 = '<b>Citations:</b>'
                    else: col1 = ''
                    if citations[i].url_from_referenced_paper and not citations[i].referencing_paper:
                        importable_citations.add(citations[i])
                    self.paper_information_pane_model.append((col1, '<i>' + str(i + 1) + ':</i> ' + pango_escape(citations[i].line_from_referenced_paper)))

                self.update_bookmark_pane_from_paper(self.displayed_paper)

                button = Gtk.ToolButton(stock_id=Gtk.STOCK_EDIT)
                button.set_tooltip_text('Edit this paper...')
                button.connect('clicked', lambda x: PaperEditGUI(paper.id))
                paper_information_toolbar.insert(button, -1)

                if self.current_playlist:
                    button = Gtk.ToolButton(stock_id=Gtk.STOCK_REMOVE)
                    button.set_tooltip_text('Remove this paper from this collection...')
                    button.connect('clicked', lambda x: self.remove_papers_from_current_playlist([paper.id]))
                    paper_information_toolbar.insert(button, -1)

                if importable_references or importable_citations:
                    import_button = Gtk.MenuToolButton(stock_id=Gtk.STOCK_ADD)
                    import_button.set_tooltip_text('Import all cited and referenced documents...(%i)' % len(importable_references.union(importable_citations)))
                    import_button.connect('clicked', lambda x: fetch_citations_via_references(importable_references.union(importable_citations)))
                    paper_information_toolbar.insert(import_button, -1)
                    import_button_menu = Gtk.Menu()
                    if importable_citations:
                        menu_item = Gtk.MenuItem('Import all cited documents (%i)' % len(importable_citations))
                        menu_item.connect('activate', lambda x: fetch_citations_via_references(importable_citations))
                        import_button_menu.append(menu_item)
                        menu_item = Gtk.MenuItem('Import specific cited document')
                        import_button_submenu = Gtk.Menu()
                        for citation in importable_citations:
                            submenu_item = Gtk.MenuItem(truncate_long_str(citation.line_from_referenced_paper))
                            submenu_item.connect('activate', lambda x: fetch_citations_via_references((citation,)))
                            import_button_submenu.append(submenu_item)
                        menu_item.set_submenu(import_button_submenu)
                        import_button_menu.append(menu_item)
                    if importable_references:
                        menu_item = Gtk.MenuItem('Import all referenced documents (%i)' % len(importable_references))
                        menu_item.connect('activate', lambda x: fetch_citations_via_references(importable_references))
                        import_button_menu.append(menu_item)
                        menu_item = Gtk.MenuItem('Import specific referenced document')
                        import_button_submenu = Gtk.Menu()
                        for reference in importable_references:
                            submenu_item = Gtk.MenuItem(truncate_long_str(reference.line_from_referencing_paper))
                            submenu_item.connect('activate', lambda x: fetch_citations_via_references((reference,)))
                            import_button_submenu.append(submenu_item)
                        menu_item.set_submenu(import_button_submenu)
                        import_button_menu.append(menu_item)
                    import_button_menu.show_all()
                    import_button.set_menu(import_button_menu)

                    button = Gtk.ToolButton() # GRAPH_ICON
                    icon = Gtk.Image()
                    icon.set_from_pixbuf(GRAPH_ICON)
                    button.set_icon_widget(icon)
                    button.set_tooltip_text('Generate document graph...')
                    button.connect('clicked', lambda x: self.graph_papers_and_authors([paper.id]))
                    paper_information_toolbar.insert(button, -1)

        else:
            # more than one paper
            self.update_bookmark_pane_from_paper(None)
            self.paper_information_pane_model.append(('<b>Number of papers:</b>', str(len(rows)) ,))

            downloadable_paper_urls = set()
            for row in rows:
                paper = liststore[row][0]
                if paper.import_url and paper.id == -1:
                    downloadable_paper_urls.add(paper.import_url)
            if len(downloadable_paper_urls):
                self.paper_information_pane_model.append(('<b>Number of new papers:</b>', str(len(downloadable_paper_urls)) ,))
                button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
                button.set_tooltip_text('Add new papers (%i) to your library...' % len(downloadable_paper_urls))
                button.connect('clicked', lambda x: fetch_citations_via_urls(downloadable_paper_urls))
                paper_information_toolbar.insert(button, -1)

            selected_valid_paper_ids = []
            for row in rows:
                if liststore[row][0].id != -1:
                    selected_valid_paper_ids.append(liststore[row][0].id)
            log_debug('selected_valid_paper_ids: %s' % str(selected_valid_paper_ids))
            if len(selected_valid_paper_ids):
                button = Gtk.ToolButton(stock_id=Gtk.STOCK_REMOVE)
                button.set_tooltip_text('Remove these papers from your library...')
                button.connect('clicked', lambda x: self.delete_papers(selected_valid_paper_ids))
                paper_information_toolbar.insert(button, -1)
                button = Gtk.ToolButton(stock_id=Gtk.STOCK_DND_MULTIPLE)
                button.set_tooltip_text('Create a new collection from these documents...')
                button.connect('clicked', lambda x: self.create_playlist(selected_valid_paper_ids))
                paper_information_toolbar.insert(button, -1)

                button = Gtk.ToolButton() # GRAPH_ICON
                icon = Gtk.Image()
                icon.set_from_pixbuf(GRAPH_ICON)
                button.set_icon_widget(icon)
                button.set_tooltip_text('Generate document graph...')
                button.connect('clicked', lambda x: self.graph_papers_and_authors(selected_valid_paper_ids))
                paper_information_toolbar.insert(button, -1)


        self.pdf_preview['current_page_number'] = 0
        self.refresh_pdf_preview_pane()

        paper_information_toolbar.show_all()

    def graph_papers_and_authors(self, paper_ids=None):
        log_debug('paper_ids: %s' % str(paper_ids))
        g = []
        g.append('graph G {')
        g.append('\toverlap=false;')
        g.append('\tnode [shape=box,style=filled,fillcolor=lightgray,fontsize=10,fontname=loma];')
        #g.append('\tsize ="10,10";')
        if paper_ids:
            papers = Paper.objects.in_bulk(paper_ids).values()
        else:
            papers = Paper.objects.all()
        for paper in papers:
            short_title = truncate_long_str(str(paper.id) + ': ' + paper.title, max_length=32)
            for author in paper.authors.all():
                g.append('\t{node [shape=oval,style=filled] "%s"};' % (author.name))
                g.append('\t"%s" -- "%s";' % (short_title, author.name))
        g.append('}')
        self.show_graph('\n'.join(g))

    def graph_authors(self, author_ids=None):
        g = []
        g.append('graph G {')
        g.append('\toverlap=false;')
        g.append('\tnode [style=filled,fillcolor=lightgray,fontsize=10,fontname=loma];')
        #g.append('\tsize ="10,10";')
        if author_ids:
            authors = Author.objects.in_bulk(author_ids).values()
        else:
            authors = Author.objects.all()
        print authors
        seen_relationships = set()
        for a1 in authors:
            for paper in a1.paper_set.all():
                for a2 in paper.authors.all():
                    if a1 != a2 and (a2.id, paper.id, a1.id) not in seen_relationships:
                        #g.append('\t{node [shape=oval,style=filled] "%s"};' % (a.name))
                        g.append('\t"%s" -- "%s";' % (a1.name, a2.name))
                        seen_relationships.add((a1.id, paper.id, a2.id))
        g.append('}')
        self.show_graph('\n'.join(g))

    def graph_papers(self, paper_ids=None):
        g = []
        g.append('digraph G {')
        g.append('\toverlap=false;')
        g.append('\tnode [shape=box,style=filled,fillcolor=lightgray,fontsize=10,fontname=loma];')
        #g.append('\tsize ="10,10";')
        if paper_ids:
            papers = Paper.objects.in_bulk(paper_ids).values()
        else:
            papers = Paper.objects.all()
        for paper in papers:
            for reference in paper.reference_set.all():
                if reference.referenced_paper:
                    g.append('\t"%s" -> "%s";' % (truncate_long_str(str(paper.id) + ': ' + paper.title, max_length=32), truncate_long_str(str(reference.referenced_paper.id) + ': ' + reference.referenced_paper.title, max_length=32)))
#                elif reference.doi_from_referenced_paper:
#                    g.append('\t"%s" -> "%s";' % (truncate_long_str(str(paper.id)+': '+paper.title, max_length=32), reference.doi_from_referenced_paper))
#                else:
#                    g.append('\t"%s" -> "%s";' % (truncate_long_str(str(paper.id)+': '+paper.title, max_length=32), 'R:'+str(reference.id)))
        g.append('}')
        self.show_graph('\n'.join(g))

    def show_graph(self, graph, command='neato'):
        import tempfile
        file = tempfile.mktemp('.pdf')
        stdin, stdout = os.popen4(command + ' -Tpdf -o"%s"' % file)
        stdin.write(graph)
        stdin.close()
        stdout.readlines()
        stdout.close()
        time.sleep(.1)
        desktop.open(file)

    def update_bookmark_pane_from_paper(self, paper):
        toolbar_bookmarks = self.ui.get_object('toolbar_bookmarks')
        for child in toolbar_bookmarks.get_children():
            toolbar_bookmarks.remove(child)
        self.treeview_bookmarks_model.clear()
        if paper:
            for bookmark in paper.bookmark_set.order_by('page'):
                try: title = str(bookmark.notes).split('\n')[0]
                except: title = str(bookmark.notes)
                self.treeview_bookmarks_model.append((bookmark.id, bookmark.page + 1, title, bookmark.updated.strftime(DATE_FORMAT), len(str(bookmark.notes).split())))
        self.refresh_pdf_preview_pane()
        self.select_bookmark_pane_item()

    def select_bookmark_pane_item(self, selection=None, bookmark_id=None):
        if selection == None:
            selection = self.ui.get_object('treeview_bookmarks').get_selection()
        toolbar_bookmarks = self.ui.get_object('toolbar_bookmarks')
        for child in toolbar_bookmarks.get_children():
            toolbar_bookmarks.remove(child)

        if bookmark_id != None:
            selection.unselect_all()
            # we're being asked to select a specific row, not handle a selection event
            for i in range(0, len(self.treeview_bookmarks_model)):
                if self.treeview_bookmarks_model[i][0] == bookmark_id:
                    selection.select_path((i,))
                    return

        try: selected_bookmark_id = self.treeview_bookmarks_model.get_value(self.ui.get_object('treeview_bookmarks').get_selection().get_selected()[1], 0)
        except: selected_bookmark_id = -1

        paper_notes = self.ui.get_object('paper_notes')
        try:
            if not self.update_paper_notes_handler_id == None:
                paper_notes.get_buffer().disconnect(self.update_paper_notes_handler_id)
            self.update_paper_notes_handler_id = None
        except:
            self.update_paper_notes_handler_id = None

        if selected_bookmark_id != -1:
                bookmark = Bookmark.objects.get(id=selected_bookmark_id)
                paper_notes.get_buffer().set_text(bookmark.notes)
                paper_notes.set_property('sensitive', True)
                self.goto_pdf_page(bookmark.page)
                self.update_paper_notes_handler_id = paper_notes.get_buffer().connect('changed', self.update_bookmark_notes, selected_bookmark_id)
        elif self.displayed_paper:
                paper_notes.get_buffer().set_text(self.displayed_paper.notes)
                paper_notes.set_property('sensitive', True)
                self.update_paper_notes_handler_id = paper_notes.get_buffer().connect('changed', self.update_paper_notes, self.displayed_paper.id)
        else:
            paper_notes.get_buffer().set_text('')
            paper_notes.set_property('sensitive', False)


        if self.displayed_paper:
            button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
            button.set_tooltip_text('Add a new page note...')
            button.connect('clicked', lambda x, paper: Bookmark.objects.create(paper=paper, page=self.pdf_preview['current_page_number']).save() or self.update_bookmark_pane_from_paper(self.displayed_paper), self.displayed_paper)
            button.show()
            toolbar_bookmarks.insert(button, -1)

        if selected_bookmark_id != -1:
            button = Gtk.ToolButton(stock_id=Gtk.STOCK_DELETE)
            button.set_tooltip_text('Delete this page note...')
            button.connect('clicked', lambda x: self.delete_bookmark(selected_bookmark_id))
            button.show()
            toolbar_bookmarks.insert(button, -1)


    def echo_objects(self, a=None, b=None, c=None, d=None, e=None, f=None, g=None):
        print a, b, c, d, e, f, g

    # FIXME: only save after some time without changes
    def update_paper_notes(self, text_buffer, id):
        log_debug('update_paper_notes called for id %s' % str(id))
        paper = Paper.objects.get(id=id)
        paper.notes = text_buffer.get_text(text_buffer.get_start_iter(),
                                           text_buffer.get_end_iter(), False)
        paper.save()

    # FIXME: only save after some time without changes
    def update_bookmark_notes(self, text_buffer, id):
        log_debug('update_bookmark_notes called for id %s' % str(id))
        bookmark = Bookmark.objects.get(id=id)
        bookmark.notes = text_buffer.get_text(text_buffer.get_start_iter(),
                                              text_buffer.get_end_iter(), False)
        bookmark.save()

    def delete_papers(self, paper_ids):
        papers = Paper.objects.in_bulk(paper_ids).values()
        paper_list_text = '\n'.join([ ('<i>"%s"</i>' % unicode(paper.title)) for paper in papers ])
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really delete the following %s?\n\n%s\n\n' % (humanize_count(len(papers), 'paper', 'papers', places= -1), paper_list_text))
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            for paper in papers:
                log_info('deleting paper: %s' % unicode(paper))
                paper.delete()
            self.refresh_middle_pane_search()

    def remove_papers_from_current_playlist(self, paper_ids):
        if not self.current_playlist: return
        try:
            for paper in Paper.objects.in_bulk(paper_ids).values():
                self.current_playlist.papers.remove(paper)
            self.current_playlist.save()
            thread.start_new_thread(self.refresh_middle_pane_from_my_library, (False,))
        except:
            traceback.print_exc()

    def delete_object(self, text, obj, update_function):
        '''
        Asks for confirmation before deleting an object and calling an update
        function (e.g. :method:`refresh_left_pane`). Is called by the
        more specific methods like :method:`delete_playlist` etc.
        '''
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO,
                                   flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup(text)
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            obj.delete()
            update_function()

    def delete_playlist(self, id):
        '''
        Ask for confirmation before deleting a document collection (playlist).
        '''
        obj = Playlist.objects.get(id=id)
        self.delete_object('Really delete this document collection?', obj,
                           self.refresh_left_pane)

    def delete_author(self, id):
        '''
        Ask for confirmation before deleting an author.
        '''
        obj = Author.objects.get(id=id)
        self.delete_object('Really delete this author?', obj,
                           self.refresh_my_library_filter_pane())

    def delete_bookmark(self, id):
        '''
        Ask for confirmation before deleting a bookmark.
        '''
        obj = Bookmark.objects.get(id=id)
        self.delete_object('Really delete this bookmark?', obj,
                           lambda : self.update_bookmark_pane_from_paper(self.displayed_paper))

    def delete_source(self, id):
        '''
        Ask for confirmation before deleting a source (e.g. a journal)
        '''
        obj = Source.objects.get(id=id)
        self.delete_object('Really delete this source?', obj,
                           self.refresh_my_library_filter_pane)

    def delete_organization(self, id):
        '''
        Ask for confirmation before deleting an organization.
        '''
        obj = Organization.objects.get(id=id)
        self.delete_object('Really delete this organization?', obj,
                           self.refresh_my_library_filter_pane)

    def refresh_middle_pane_from_my_library(self, refresh_library_filter_pane=True):
        try:
            rows = []
            my_library_filter_pane = self.ui.get_object('my_library_filter_pane')

            if not self.current_playlist and self.current_papers == None:

                search_text = self.ui.get_object('middle_pane_search').get_text().strip()
                if search_text:
                    my_library_filter_pane.hide()
                    paper_ids = set()
                    for s in search_text.split():
                        for paper in Paper.objects.filter(Q(title__icontains=s) | Q(doi__icontains=s) | Q(source_session__icontains=s) | Q(abstract__icontains=s) | Q(extracted_text__icontains=s)):
                            paper_ids.add(paper.id)
                        for sponsor in Sponsor.objects.filter(name__icontains=s):
                            for paper in sponsor.paper_set.all(): paper_ids.add(paper.id)
                        for author in Author.objects.filter(Q(name__icontains=s) | Q(location__icontains=s)):
                            for paper in author.paper_set.all(): paper_ids.add(paper.id)
                        for source in Source.objects.filter(Q(name__icontains=s) | Q(issue__icontains=s) | Q(location__icontains=s)):
                            for paper in source.paper_set.all(): paper_ids.add(paper.id)
                        for organization in Organization.objects.filter(Q(name__icontains=s) | Q(location__icontains=s)):
                            for paper in organization.paper_set.all(): paper_ids.add(paper.id)
                        for publisher in Publisher.objects.filter(name__icontains=s):
                            for source in publisher.source_set.all():
                                for paper in source.paper_set.all(): paper_ids.add(paper.id)
                        for reference in Reference.objects.filter(Q(line_from_referencing_paper__icontains=s) | Q(doi_from_referencing_paper__icontains=s)):
                            paper_ids.add(reference.referencing_paper.id)
                        for reference in Reference.objects.filter(Q(line_from_referenced_paper__icontains=s) | Q(doi_from_referenced_paper__icontains=s)):
                            paper_ids.add(reference.referenced_paper.id)
                        for bookmark in Bookmark.objects.filter(notes__icontains=s):
                            paper_ids.add(bookmark.paper.id)
                    papers = Paper.objects.in_bulk(list(paper_ids)).values()
                else:
                    if refresh_library_filter_pane:
                        self.refresh_my_library_filter_pane()
                        my_library_filter_pane.show()
                    paper_query = Paper.objects.order_by('title')

                    filter_liststore, filter_rows = self.ui.get_object('author_filter').get_selection().get_selected_rows()
                    q = None
                    for treepath in filter_rows:
                        row = filter_liststore[treepath]
                        log_debug('row[0]: %s' % row[0])
                        if q == None: q = Q(authors__id=row[0])
                        else: q = q | Q(authors__id=row[0])
                    log_debug('q: %s' % str(q))
                    if q: paper_query = paper_query.filter(q)

                    filter_liststore, filter_rows = self.ui.get_object('source_filter').get_selection().get_selected_rows()
                    q = None
                    for treepath in filter_rows:
                        row = filter_liststore[treepath]
                        if q == None: q = Q(source__id=row[0])
                        else: q = q | Q(source__id=row[0])
                    if q: paper_query = paper_query.filter(q)

                    filter_liststore, filter_rows = self.ui.get_object('organization_filter').get_selection().get_selected_rows()
                    q = None
                    for treepath in filter_rows:
                        row = filter_liststore[treepath]
                        if q == None: q = Q(organizations__id=row[0])
                        else: q = q | Q(organizations__id=row[0])
                    if q: paper_query = paper_query.filter(q)

                    papers = paper_query.distinct()

            else:
                my_library_filter_pane.hide()
                if self.current_playlist:
                    papers = self.current_playlist.get_papers_in_order()
                elif self.current_papers != None:
                    papers = self.current_papers
                else:
                    papers = []

            log_debug('papers: %s' % str(papers))
            for paper in papers:
                authors = []
                for author in paper.authors.order_by('id'):
                    authors.append(unicode(author.name))
                if paper.full_text and os.path.isfile(paper.full_text.path):
                    icon = self.ui.get_object('middle_top_pane').render_icon(Gtk.STOCK_DND, Gtk.IconSize.MENU)
                else:
                    icon = None
                if paper.source:
                    journal = paper.source.name
                    if paper.source.publication_date:
                        pub_year = str(paper.source.publication_date.year)
                    else:
                        pub_year = ''
                else:
                    journal = ''
                    pub_year = ''
                rows.append((
                    paper.id,
                    pango_escape(', '.join(authors)),
                    pango_escape(paper.title),
                    pango_escape(journal),
                    pub_year,
                    (paper.rating + 10) * 5,
                    paper.abstract,
                    icon, # icon
                    paper.import_url, # import_url
                    paper.doi, # doi
                    paper.created.strftime(DATE_FORMAT), # created
                    paper.updated.strftime(DATE_FORMAT), # updated
                    '', # empty_str
                    paper.pubmed_id, # pubmed_id
                    None,
                    None
                ))
            self.middle_top_pane_model.clear()
            for paper in papers:
                self.middle_top_pane_model.append((paper, ))
            self.refresh_my_library_count()
        except:
            traceback.print_exc()

    def refresh_my_library_count(self):
        selection = self.ui.get_object('left_pane_selection')
        liststore, rows = selection.get_selected()
        liststore.set_value(self.left_pane_model.get_iter((0,)), 0,
                            '<b>My Library</b>  <span foreground="#888888">(%i)</span>' % Paper.objects.count())
        

    def refresh_middle_pane_from_external(self, search_info, results):
        ''' 
        This callback is called when an external search has finished and
        returned results. `search_info` has to be a tuple of a search search_providers
        label and the original search string, `results` is a list of dictionaries
        containing the search results, e.g. 
        [{'authors' : ['Author A', 'Author B], 'title': 'A title'},
         {'authors' : ['Author C'], 'title': 'Another title'}]
        
        Before the search results are actually displayed in the GUI, it is
        checked whether the same search search_providers is still active and the same
        search string is still given. This should avoid situations where a 
        previous search result arrives later and would otherwise overwrite the
        results of a later search.
        '''

        label, search_string = search_info
        search_provider = self.search_providers[label]
        log_info('Received results for %s: %s' % (search_provider.name,
                                                  search_string))

        liststore, row = self.ui.get_object('left_pane_selection').get_selected()
        current_label = liststore[row][4]
        current_search_text = self.ui.get_object('middle_pane_search').get_text().strip()

        if label != current_label or search_string != current_search_text:
            log_info('Results are no longer wanted.')
            return

        log_info('Results are still wanted, processing further...')

        rows = []
        for info in results:
            try:
                unique_key = search_provider.unique_key
                kwds = {unique_key : info.get(unique_key)}
                existing_paper = Paper.objects.filter(**kwds)
                if not existing_paper:
                    raise Paper.DoesNotExist()
                existing_paper = existing_paper[0]
                info['id'] = existing_paper.id
                info['created'] = existing_paper.created
                info['updated'] = existing_paper.updated
                if existing_paper.full_text and \
                           os.path.isfile(existing_paper.full_text.path):
                    info['icon'] = self.ui.get_object('middle_top_pane').\
                                    render_icon(Gtk.STOCK_DND,
                                    Gtk.IconSize.MENU)
            except Paper.DoesNotExist:
                pass

            # Add information to table 
            rows.append(row_from_dictionary(info, search_provider))

        self.middle_top_pane_model.clear()
        for row in rows:
            self.middle_top_pane_model.append(row)


class AuthorEditGUI:
    def __init__(self, author_id, callback_on_save=None):
        self.callback_on_save = callback_on_save
        if author_id == -1:
            self.author = Author.objects.create()
        else:
            self.author = Author.objects.get(id=author_id)
        self.ui = Gtk.Builder()
        self.ui.add_from_file(os.path.join(BASE_DIR, 'data', 'author_edit_gui.xml'))
        self.author_edit_dialog = self.ui.get_object('author_edit_dialog')
        self.author_edit_dialog.connect("delete-event", lambda x, y : self.author_edit_dialog.destroy)
        self.ui.get_object('button_connect').connect("clicked", lambda x: self.show_connect_menu())
        self.ui.get_object('button_cancel').connect("clicked", lambda x: self.author_edit_dialog.destroy())
        self.ui.get_object('button_delete').connect("clicked", lambda x: self.delete())
        self.ui.get_object('button_save').connect("clicked", lambda x: self.save())
        self.ui.get_object('entry_name').set_text(self.author.name)
        self.ui.get_object('label_paper_count').set_text(str(self.author.paper_set.count()))
        self.ui.get_object('notes').get_buffer().set_text(self.author.notes)
        self.ui.get_object('notes').modify_base(Gtk.StateType.NORMAL, Gdk.color_parse("#fff7e8"))
        self.ui.get_object('rating').set_value(self.author.rating)

        treeview_organizations = self.ui.get_object('treeview_organizations')
        # id, org, location
        self.organizations_model = Gtk.ListStore(int, str, str)
        treeview_organizations.set_model(self.organizations_model)
        treeview_organizations.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        renderer = Gtk.CellRendererText()
        renderer.set_property('editable', True)
        renderer.connect('edited', lambda cellrenderertext, path, new_text: self.organizations_model.set_value(self.organizations_model.get_iter(path), 1, new_text) or self.update_organization_name(self.organizations_model.get_value(self.organizations_model.get_iter(path), 0), new_text))
        column = Gtk.TreeViewColumn("Organization", renderer, text=1)
        column.set_sort_column_id(1)
        column.set_min_width(128)
        column.set_expand(True)
        treeview_organizations.append_column(column)
        renderer = Gtk.CellRendererText()
        renderer.set_property('editable', True)
        renderer.connect('edited', lambda cellrenderertext, path, new_text: self.organizations_model.set_value(self.organizations_model.get_iter(path), 2, new_text) or self.update_organization_location(self.organizations_model.get_value(self.organizations_model.get_iter(path), 0), new_text))
        column = Gtk.TreeViewColumn("Location", renderer, text=2)
        column.set_sort_column_id(2)
        column.set_min_width(128)
        column.set_expand(True)
        treeview_organizations.append_column(column)
        make_all_columns_resizeable_clickable_ellipsize(treeview_organizations.get_columns())
        treeview_organizations.connect('button-press-event', self.handle_organizations_button_press_event)
        for organization in self.author.organizations.order_by('name'):
            self.organizations_model.append((organization.id, organization.name, organization.location))

        button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
        button.set_tooltip_text('Add an organization...')
        menu = self.get_new_organizations_menu()
        menu.attach_to_widget(button, None)
        button.connect('clicked', lambda x: menu.popup(None, None, None, None, 0, 0))
        button.show()
        self.ui.get_object('toolbar_organizations').insert(button, -1)

        self.author_edit_dialog.show()

    def delete(self):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really delete this author?')
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.author.delete()
            self.author_edit_dialog.destroy()
            main_gui.refresh_middle_pane_search()

    def update_organization_name(self, id, new_text):
        organziation = Organization.objects.get(id=id)
        organziation.name = new_text.strip()
        organziation.save()

    def update_organization_location(self, id, new_text):
        organziation = Organization.objects.get(id=id)
        organziation.location = new_text.strip()
        organziation.save()

    def handle_organizations_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.organizations_model.get_value(self.organizations_model.get_iter(path), 0)
                if id >= 0:
                    menu = Gtk.Menu()
                    remove = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_REMOVE, None)
                    remove.connect('activate', lambda x: self.organizations_model.remove(self.organizations_model.get_iter(path)))
                    menu.append(remove)
                    menu_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_ADD, None)
                    menu_item.set_submenu(self.get_new_organizations_menu())
                    menu.append(menu_item)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def get_new_organizations_menu(self):
        button_submenu = Gtk.Menu()
        org_ids = set()
        for organization in self.organizations_model:
            org_ids.add(organization[0])

        for organization in Organization.objects.order_by('name'):
            if organization.id not in org_ids and len(organization.name):
                submenu_item = Gtk.MenuItem(truncate_long_str(organization.name))
                submenu_item.connect('activate', lambda x, r: self.organizations_model.append(r), (organization.id, organization.name, organization.location))
                button_submenu.append(submenu_item)
        submenu_item = Gtk.MenuItem('New...')
        new_org = Organization.objects.create()
        submenu_item.connect('activate', lambda x, new_org: new_org.save() or self.organizations_model.append((new_org.id, new_org.name, new_org.location)), new_org)
        button_submenu.append(submenu_item)
        button_submenu.show_all()
        return button_submenu


    def save(self):
        self.author.name = self.ui.get_object('entry_name').get_text()
        text_buffer = self.ui.get_object('notes').get_buffer()
        self.author.notes = text_buffer.get_text(text_buffer.get_start_iter(),
                                                 text_buffer.get_end_iter(),
                                                 False)
        self.author.rating = round(self.ui.get_object('rating').get_value())
        self.author.save()
        org_ids = set()
        for organization in self.organizations_model:
            org_ids.add(organization[0]) 
        self.author.organizations = Organization.objects.in_bulk(list(org_ids))
        self.author_edit_dialog.destroy()
        if self.callback_on_save:
            self.callback_on_save(self.author)
        main_gui.refresh_middle_pane_search()

    def connect(self, author, id):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really merge this author with "%s"?' % author.name)
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            author.merge(id)
            self.author_edit_dialog.destroy()
            main_gui.refresh_middle_pane_search()

    def show_connect_menu(self):
        menu = Gtk.Menu()
        for author in Author.objects.order_by('name'):
            if author.id != self.author.id:
                menu_item = Gtk.MenuItem(truncate_long_str(author.name))
                menu_item.connect('activate', lambda x, author, id: self.connect(author, id), author, self.author.id)
                menu.append(menu_item)
        menu.attach_to_widget(self.ui.get_object('treeview_organizations'), None)
        menu.popup(None, None, None, None, 0, 0)
        menu.show_all()


class OrganizationEditGUI:
    def __init__(self, id):
        self.organization = Organization.objects.get(id=id)
        self.ui = Gtk.Builder()
        self.ui.add_from_file(os.path.join(BASE_DIR, 'data', 'organization_edit_gui.xml'))
        self.edit_dialog = self.ui.get_object('organization_edit_dialog')
        self.edit_dialog.connect("delete-event", lambda x, y : self.edit_dialog.destroy)
        self.ui.get_object('button_connect').connect("clicked", lambda x: self.show_connect_menu())
        self.ui.get_object('button_cancel').connect("clicked", lambda x: self.edit_dialog.destroy())
        self.ui.get_object('button_delete').connect("clicked", lambda x: self.delete())
        self.ui.get_object('button_save').connect("clicked", lambda x: self.save())
        self.ui.get_object('entry_name').set_text(self.organization.name)
        self.ui.get_object('entry_location').set_text(self.organization.location)
        self.edit_dialog.show()

    def delete(self):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really delete this organization?')
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.organization.delete()
            self.edit_dialog.destroy()
            main_gui.refresh_middle_pane_search()

    def save(self):
        self.organization.name = self.ui.get_object('entry_name').get_text()
        self.organization.location = self.ui.get_object('entry_location').get_text()
        self.organization.save()
        self.edit_dialog.destroy()
        main_gui.refresh_middle_pane_search()

    def connect(self, organization, id):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really merge this organization with "%s"?' % organization.name)
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            organization.merge(id)
            self.edit_dialog.destroy()
            main_gui.refresh_middle_pane_search()

    def show_connect_menu(self):
        menu = Gtk.Menu()
        for organization in Organization.objects.order_by('name'):
            if organization.id != self.organization.id:
                menu_item = Gtk.MenuItem(truncate_long_str(organization.name))
                menu_item.connect('activate', lambda x, organization, id: self.connect(organization, id), organization, self.organization.id)
                menu.append(menu_item)
        menu.attach_to_widget(self.edit_dialog, None)
        menu.popup(None, None, None, None, 0, 0)
        menu.show_all()



class SourceEditGUI:
    def __init__(self, id):
        self.source = Source.objects.get(id=id)
        self.ui = Gtk.Builder()
        self.ui.add_from_file(os.path.join(BASE_DIR, 'data', 'source_edit_gui.xml'))
        self.edit_dialog = self.ui.get_object('source_edit_dialog')
        self.edit_dialog.connect("delete-event", lambda x, y : self.edit_dialog.destroy)
        self.ui.get_object('button_connect').connect("clicked", lambda x: self.show_connect_menu())
        self.ui.get_object('button_cancel').connect("clicked", lambda x: self.edit_dialog.destroy())
        self.ui.get_object('button_delete').connect("clicked", lambda x: self.delete())
        self.ui.get_object('button_save').connect("clicked", lambda x: self.save())
        self.ui.get_object('entry_name').set_text(self.source.name)
        self.ui.get_object('entry_location').set_text(self.source.location)
        self.ui.get_object('entry_issue').set_text(self.source.issue)
        self.edit_dialog.show()

    def delete(self):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really delete this source?')
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.source.delete()
            self.edit_dialog.destroy()
            main_gui.refresh_middle_pane_search()

    def save(self):
        self.source.name = self.ui.get_object('entry_name').get_text()
        self.source.location = self.ui.get_object('entry_location').get_text()
        self.source.issue = self.ui.get_object('entry_issue').get_text()
        self.source.save()
        self.edit_dialog.destroy()
        main_gui.refresh_middle_pane_search()

    def connect(self, source, id):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really merge this source with "%s"?' % source.name)
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            source.merge(id)
            self.edit_dialog.destroy()
            main_gui.refresh_middle_pane_search()

    def show_connect_menu(self):
        menu = Gtk.Menu()
        for source in Source.objects.order_by('name'):
            if source.id != self.source.id:
                menu_item = Gtk.MenuItem(truncate_long_str(source.name))
                menu_item.connect('activate', lambda x, source, id: self.connect(source, id), source, self.source.id)
                menu.append(menu_item)
        menu.attach_to_widget(self.ui.get_object('source_edit_dialog'), None)
        menu.popup(None, None, None, None, 0, 0)
        menu.show_all()



class ReferenceEditGUI:
    def __init__(self, id):
        self.reference = Reference.objects.get(id=id)
        self.ui = Gtk.Builder()
        self.ui.add_from_file(os.path.join(BASE_DIR, 'data', 'reference_edit_gui.xml'))
        self.edit_dialog = self.ui.get_object('reference_edit_dialog')
        self.edit_dialog.connect("delete-event", lambda x, y : self.edit_dialog.destroy)
        self.ui.get_object('button_cancel').connect("clicked", lambda x: self.edit_dialog.destroy())
        self.ui.get_object('button_delete').connect("clicked", lambda x: self.delete())
        self.ui.get_object('button_save').connect("clicked", lambda x: self.save())
        self.ui.get_object('entry_line_from_referencing_paper').set_text(self.reference.line_from_referencing_paper)
        self.ui.get_object('entry_doi_from_referencing_paper').set_text(self.reference.doi_from_referencing_paper)
        self.ui.get_object('entry_url_from_referencing_paper').set_text(self.reference.url_from_referencing_paper)

        combobox_referencing_paper = self.ui.get_object('combobox_referencing_paper')
        combobox_referenced_paper = self.ui.get_object('combobox_referenced_paper')
        papers = [ (paper.id, truncate_long_str(paper.pretty_string())) for paper in Paper.objects.order_by('title') ]
        papers.insert(0, (-1, '(not in local library)'))
        set_model_from_list(combobox_referencing_paper, papers)
        if self.reference.referencing_paper:
            combobox_referencing_paper.set_active(index_of_in_list_of_lists(value=self.reference.referencing_paper.id, list=papers, column=0, not_found= -1))
        else:
            combobox_referencing_paper.set_active(0)
        set_model_from_list(combobox_referenced_paper, papers)
        if self.reference.referenced_paper:
            combobox_referenced_paper.set_active(index_of_in_list_of_lists(value=self.reference.referenced_paper.id, list=papers, column=0, not_found= -1))
        else:
            combobox_referenced_paper.set_active(0)

        self.edit_dialog.show()

    def delete(self):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really delete this reference?')
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.reference.delete()
            self.edit_dialog.destroy()

    def save(self):
        self.reference.line_from_referencing_paper = self.ui.get_object('entry_line_from_referencing_paper').get_text()
        self.reference.doi_from_referencing_paper = self.ui.get_object('entry_doi_from_referencing_paper').get_text()
        self.reference.url_from_referencing_paper = self.ui.get_object('entry_url_from_referencing_paper').get_text()
        print "self.ui.get_object('combobox_referencing_paper').get_active()", self.ui.get_object('combobox_referencing_paper').get_active()
        referencing_paper_id = self.ui.get_object('combobox_referencing_paper').get_model()[ self.ui.get_object('combobox_referencing_paper').get_active() ][0]
        try: self.reference.referencing_paper = Paper.objects.get(id=referencing_paper_id)
        except: self.reference.referencing_paper = None
        referenced_paper_id = self.ui.get_object('combobox_referenced_paper').get_model()[ self.ui.get_object('combobox_referenced_paper').get_active() ][0]
        try: self.reference.referenced_paper = Paper.objects.get(id=referenced_paper_id)
        except: self.reference.referenced_paper = None
        self.reference.save()
        self.edit_dialog.destroy()


class CitationEditGUI:
    def __init__(self, id):
        self.reference = Reference.objects.get(id=id)
        self.ui = Gtk.Builder()
        self.ui.add_from_file(os.path.join(BASE_DIR, 'data', 'citation_edit_gui.xml'))
        self.edit_dialog = self.ui.get_object('citation_edit_dialog')
        self.edit_dialog.connect("delete-event", lambda x, y : self.edit_dialog.destroy)
        self.ui.get_object('button_cancel').connect("clicked", lambda x: self.edit_dialog.destroy())
        self.ui.get_object('button_delete').connect("clicked", lambda x: self.delete())
        self.ui.get_object('button_save').connect("clicked", lambda x: self.save())
        self.ui.get_object('entry_line_from_referenced_paper').set_text(self.reference.line_from_referenced_paper)
        self.ui.get_object('entry_doi_from_referenced_paper').set_text(self.reference.doi_from_referenced_paper)
        self.ui.get_object('entry_url_from_referenced_paper').set_text(self.reference.url_from_referenced_paper)

        combobox_referencing_paper = self.ui.get_object('combobox_referencing_paper')
        combobox_referenced_paper = self.ui.get_object('combobox_referenced_paper')
        papers = [ (paper.id, truncate_long_str(paper.pretty_string())) for paper in Paper.objects.order_by('title') ]
        papers.insert(0, (-1, '(not in local library)'))
        set_model_from_list(combobox_referencing_paper, papers)
        if self.reference.referencing_paper:
            combobox_referencing_paper.set_active(index_of_in_list_of_lists(value=self.reference.referencing_paper.id, list=papers, column=0, not_found= -1))
        else:
            combobox_referencing_paper.set_active(0)
        set_model_from_list(combobox_referenced_paper, papers)
        if self.reference.referenced_paper:
            combobox_referenced_paper.set_active(index_of_in_list_of_lists(value=self.reference.referenced_paper.id, list=papers, column=0, not_found= -1))
        else:
            combobox_referenced_paper.set_active(0)

        self.edit_dialog.show()

    def delete(self):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really delete this reference?')
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.reference.delete()
            self.edit_dialog.destroy()

    def save(self):
        self.reference.line_from_referenced_paper = self.ui.get_object('entry_line_from_referenced_paper').get_text()
        self.reference.doi_from_referenced_paper = self.ui.get_object('entry_doi_from_referenced_paper').get_text()
        self.reference.url_from_referenced_paper = self.ui.get_object('entry_url_from_referenced_paper').get_text()
        referencing_paper_id = self.ui.get_object('combobox_referencing_paper').get_model()[ self.ui.get_object('combobox_referencing_paper').get_active() ][0]
        try: self.reference.referencing_paper = Paper.objects.get(id=referencing_paper_id)
        except: self.reference.referencing_paper = None
        referenced_paper_id = self.ui.get_object('combobox_referenced_paper').get_model()[ self.ui.get_object('combobox_referenced_paper').get_active() ][0]
        try: self.reference.referenced_paper = Paper.objects.get(id=referenced_paper_id)
        except: self.reference.referenced_paper = None
        self.reference.save()
        self.edit_dialog.destroy()



class PaperEditGUI:
    def __init__(self, id):
        self.paper = Paper.objects.get(id=id)
        self.ui = Gtk.Builder()
        self.ui.add_from_file(os.path.join(BASE_DIR, 'data', 'paper_edit_gui.xml'))
        self.edit_dialog = self.ui.get_object('paper_edit_dialog')
        self.edit_dialog.connect("delete-event", lambda x, y : self.edit_dialog.destroy)
        self.ui.get_object('button_cancel').connect("clicked", lambda x: self.edit_dialog.destroy())
        self.ui.get_object('button_delete').connect("clicked", lambda x: self.delete())
        self.ui.get_object('button_save').connect("clicked", lambda x: self.save())
        self.ui.get_object('toolbutton_refresh_from_pdf').connect("clicked", lambda x: self.toolbutton_refresh_extracted_text_from_pdf())
        self.ui.get_object('entry_title').set_text(self.paper.title)
        self.ui.get_object('entry_doi').set_text(self.paper.doi)
        self.ui.get_object('entry_import_url').set_text(self.paper.import_url)
        self.ui.get_object('textview_abstract').get_buffer().set_text(self.paper.abstract)
        self.ui.get_object('textview_bibtex').get_buffer().set_text(self.paper.bibtex)
        self.ui.get_object('textview_extracted_text').get_buffer().set_text(self.paper.extracted_text)
        if self.paper.full_text:
            self.ui.get_object('filechooserbutton').set_filename(self.paper.full_text.path)
        self.ui.get_object('rating').set_value(self.paper.rating)
        self.ui.get_object('spinbutton_read_count').set_value(self.paper.read_count)

        treeview_authors = self.ui.get_object('treeview_authors')
        # id, name
        self.authors_model = Gtk.ListStore(int, str)
        treeview_authors.set_model(self.authors_model)
        treeview_authors.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Author", renderer, text=1)
        column.set_expand(True)
        treeview_authors.append_column(column)
        make_all_columns_resizeable_clickable_ellipsize(treeview_authors.get_columns())
        treeview_authors.connect('button-press-event', self.handle_authors_button_press_event)
        for author in self.paper.get_authors_in_order():
            self.authors_model.append((author.id, author.name))

        button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
        button.set_tooltip_text('Add an author...')
        menu = self.get_new_authors_menu()
        menu.attach_to_widget(button, None)
        button.connect('clicked', lambda x: menu.popup(None, None, None, None, 0, 0))
        button.show()
        self.ui.get_object('toolbar_authors').insert(button, -1)

        self.init_references_tab()
        self.init_citations_tab()

        self.edit_dialog.show()

    def toolbutton_refresh_extracted_text_from_pdf(self):
        if self.paper.full_text:
            fp = open(self.paper.full_text.path, 'rb')
            paper_info = pdf_file.get_paper_info_from_pdf(fp.read())
            fp.close()
        self.paper.extracted_text = paper_info.get('extracted_text')
        self.ui.get_object('textview_extracted_text').get_buffer().set_text(self.paper.extracted_text)
        self.paper.save()

    def init_references_tab(self):
        treeview_references = self.ui.get_object('treeview_references')
        # id, line, number, pix_buf
        self.references_model = Gtk.ListStore(int, str, str, GdkPixbuf.Pixbuf)
        treeview_references.set_model(self.references_model)
        treeview_references.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        treeview_references.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=2))
        column = Gtk.TreeViewColumn()
        renderer = Gtk.CellRendererPixbuf()
        column.pack_start(renderer, False)
        column.add_attribute(renderer, 'pixbuf', 3)
        renderer = Gtk.CellRendererText()
        column.pack_start(renderer, True)
        column.add_attribute(renderer, 'markup', 1)
        column.set_expand(True)
        treeview_references.append_column(column)
        #make_all_columns_resizeable_clickable_ellipsize( treeview_references.get_columns() )
        treeview_references.connect('button-press-event', self.handle_references_button_press_event)
        references = self.paper.reference_set.order_by('id')
        for i in range(0, len(references)):
            if references[i].referenced_paper and references[i].referenced_paper.full_text and os.path.isfile(references[i].referenced_paper.full_text.path):
                icon = treeview_references.render_icon(Gtk.STOCK_DND, Gtk.IconSize.MENU)
            else:
                icon = None
            self.references_model.append((references[i].id, references[i].line_from_referencing_paper , '<i>' + str(i + 1) + ':</i>', icon))

        button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
        button.set_tooltip_text('Add a reference...')
        menu = self.get_new_authors_menu()
        menu.attach_to_widget(button, None)
        button.connect('clicked', lambda x: menu.popup(None, None, None, None, 0, 0))
        button.show()
        #self.ui.get_object('toolbar_references').insert( button, -1 )

    def init_citations_tab(self):
        treeview_citations = self.ui.get_object('treeview_citations')
        # id, line, number, pix_buf
        self.citations_model = Gtk.ListStore(int, str, str, GdkPixbuf.Pixbuf)
        treeview_citations.set_model(self.citations_model)
        treeview_citations.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        #treeview_citations.append_column( Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=2) )
        column = Gtk.TreeViewColumn()
        renderer = Gtk.CellRendererPixbuf()
        column.pack_start(renderer, False)
        column.add_attribute(renderer, 'pixbuf', 3)
        renderer = Gtk.CellRendererText()
        column.pack_start(renderer, True)
        column.add_attribute(renderer, 'markup', 1)
        column.set_expand(True)
        treeview_citations.append_column(column)
        #make_all_columns_resizeable_clickable_ellipsize( treeview_citations.get_columns() )
        treeview_citations.connect('button-press-event', self.handle_citations_button_press_event)
        references = self.paper.citation_set.order_by('id')
        for i in range(0, len(references)):
            if references[i].referencing_paper and references[i].referencing_paper.full_text and os.path.isfile(references[i].referencing_paper.full_text.path):
                icon = treeview_citations.render_icon(Gtk.STOCK_DND, Gtk.IconSize.MENU)
            else:
                icon = None
            self.citations_model.append((references[i].id, references[i].line_from_referenced_paper , '<i>' + str(i + 1) + ':</i>', icon))

        button = Gtk.ToolButton(stock_id=Gtk.STOCK_ADD)
        button.set_tooltip_text('Add a reference...')
        menu = self.get_new_authors_menu()
        menu.attach_to_widget(button, None)
        button.connect('clicked', lambda x: menu.popup(None, None, None, None, 0, 0))
        button.show()
        #self.ui.get_object('toolbar_references').insert( button, -1 )

    def delete(self):
        dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, flags=Gtk.DialogFlags.MODAL)
        dialog.set_markup('Really delete this paper?')
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.paper.delete()
            self.edit_dialog.destroy()
            main_gui.refresh_middle_pane_search()

    def save(self):
        self.paper.title = self.ui.get_object('entry_title').get_text()
        self.paper.doi = self.ui.get_object('entry_doi').get_text()
        self.paper.import_url = self.ui.get_object('entry_import_url').get_text()
        text_buffer = self.ui.get_object('textview_abstract').get_buffer()
        self.paper.abstract = text_buffer.get_text(text_buffer.get_start_iter(),
                                                   text_buffer.get_end_iter(),
                                                   False)
        text_buffer = self.ui.get_object('textview_bibtex').get_buffer()
        self.paper.bibtex = text_buffer.get_text(text_buffer.get_start_iter(),
                                                 text_buffer.get_end_iter(),
                                                 False)
        self.paper.rating = round(self.ui.get_object('rating').get_value())
        self.paper.read_count = self.ui.get_object('spinbutton_read_count').get_value()
        new_file_name = self.ui.get_object('filechooserbutton').get_filename()
        if new_file_name and (not self.paper.full_text or
                              new_file_name != self.paper.full_text.path):
            try:
                ext = new_file_name[ new_file_name.rfind('.') + 1: ]
            except:
                ext = 'unknown'
            full_text_filename = defaultfilters.slugify(self.paper.doi) + '_' + defaultfilters.slugify(self.paper.title) + '.' + defaultfilters.slugify(ext)
            self.paper.save_file(full_text_filename, open(new_file_name, 'r').read())

        self.paper.authors.clear()

        for row in self.authors_model:
            self.paper.authors.add(Author.objects.get(id=row[0]))

        self.paper.save()
        self.edit_dialog.destroy()
        main_gui.refresh_middle_pane_search()

    def handle_authors_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.authors_model.get_value(self.authors_model.get_iter(path), 0)
                if id >= 0:
                    menu = Gtk.Menu()
                    remove = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_REMOVE, None)
                    remove.connect('activate', lambda x: self.authors_model.remove(self.authors_model.get_iter(path)))
                    menu.append(remove)
                    menu_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_ADD, None)
                    menu_item.set_submenu(self.get_new_authors_menu())
                    menu.append(menu_item)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_references_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.references_model.get_value(self.references_model.get_iter(path), 0)
                if id >= 0:
                    reference = Reference.objects.get(id=id)
                    menu = Gtk.Menu()
                    if reference.referenced_paper and reference.referenced_paper.full_text and os.path.isfile(reference.referenced_paper.full_text.path):
                        menu_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_OPEN, None)
                        menu_item.connect('activate', lambda x: reference.referenced_paper.open())
                        menu.append(menu_item)
                    menu_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_EDIT, None)
                    menu_item.connect('activate', lambda x: ReferenceEditGUI(reference.id))
                    menu.append(menu_item)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def handle_citations_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                id = self.citations_model.get_value(self.citations_model.get_iter(path), 0)
                if id >= 0:
                    reference = Reference.objects.get(id=id)
                    menu = Gtk.Menu()
                    if reference.referencing_paper and reference.referencing_paper.full_text and os.path.isfile(reference.referencing_paper.full_text.path):
                        menu_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_OPEN, None)
                        menu_item.connect('activate', lambda x: reference.referenced_paper.open())
                        menu.append(menu_item)
                    menu_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_EDIT, None)
                    menu_item.connect('activate', lambda x: CitationEditGUI(reference.id))
                    menu.append(menu_item)
                    menu.show_all()
                    menu.attach_to_widget(treeview, None)
                    menu.popup(None, None, None, None, event.button, event.get_time())
            return True

    def get_new_authors_menu(self):
        button_submenu = Gtk.Menu()
        author_ids = set()
        for author_id, _ in self.authors_model:
            author_ids.add(author_id)
        for author in Author.objects.order_by('name'):
            if author.id not in author_ids and len(author.name):
                submenu_item = Gtk.MenuItem(truncate_long_str(author.name))
                submenu_item.connect('activate', lambda x, r: self.authors_model.append(r), (author.id, author.name))
                button_submenu.append(submenu_item)
        submenu_item = Gtk.MenuItem('New...')
        submenu_item.connect('activate', lambda x: AuthorEditGUI(-1, callback_on_save=self.add_new_author))
        button_submenu.append(submenu_item)
        button_submenu.show_all()
        return button_submenu

    def add_new_author(self, new_author):
        self.authors_model.append((new_author.id, new_author.name))

def init_db():
    import django.core.management.commands.syncdb
    django.core.management.commands.syncdb.Command().handle_noargs(interactive=False)


def main(argv):
    '''
    Starts gpapers with the given command line arguments `argv`.
    Currently all arguments are ignored by gpapers but may be used to give
    general GTK parameters.
    '''
    Gtk.init(argv)
    MEDIA_ROOT = gpapers.settings.MEDIA_ROOT

    log_info('using database at %s' % MEDIA_ROOT)

    if not os.path.isdir(MEDIA_ROOT):
        os.mkdir(MEDIA_ROOT)
    if not os.path.isdir(os.path.join(MEDIA_ROOT, 'papers')):
        os.mkdir(os.path.join(MEDIA_ROOT, 'papers'))
    global main_gui
    init_db()
    main_gui = MainGUI()
    importer.active_threads = main_gui.active_threads
    Gtk.main()

