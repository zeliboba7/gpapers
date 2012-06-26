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

import hashlib, os
from datetime import datetime

from django.db import models
import django.core.files.base

from gi.repository import Gtk
from gi.repository import Gdk

from gpapers.logger import log_debug, log_error

class Publisher(models.Model):

    name = models.CharField(max_length='1024')
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Admin:
        list_display = ('id', 'name',)

    def __unicode__(self):
        return self.name


class Source(models.Model):

    name = models.CharField(max_length='1024')
    issue = models.CharField(max_length='1024')
    acm_toc_url = models.URLField()
    location = models.CharField(max_length='1024', blank=True)
    publication_date = models.DateField(null=True)
    publisher = models.ForeignKey(Publisher, null=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def merge(self, id):
        if id == self.id:
            return
        other_source = Source.objects.get(id=id)
        if not self.publisher:
            self.publisher = other_source.publisher
        for paper in other_source.paper_set.all():
            self.paper_set.add(paper)
        other_source.delete()

    class Admin:
        list_display = ('id', 'name', 'issue', 'location', 'publisher', 'publication_date',)

    def __unicode__(self):
        return self.name


class Organization(models.Model):

    name = models.CharField(max_length='1024')
    location = models.CharField(max_length='1024', blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def merge(self, id):
        if id == self.id:
            return
        other_organization = Organization.objects.get(id=id)
        for author in other_organization.author_set.all():
            self.author_set.add(author)
        for paper in other_organization.paper_set.all():
            self.paper_set.add(paper)
        other_organization.delete()

    class Admin:
        list_display = ('id', 'name', 'location')

    def __unicode__(self):
        return self.name


class Author(models.Model):

    name = models.CharField(max_length='1024')
    location = models.CharField(max_length='1024', blank=True)
    organizations = models.ManyToManyField(Organization)
    department = models.CharField(max_length='1024', blank=True)
    notes = models.TextField(blank=True)
    rating = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def merge(self, id):
        if id == self.id:
            return
        other_author = Author.objects.get(id=id)
        for organization in other_author.organizations.all():
            self.organizations.add(organization)
        from django.db import connection
        cursor = connection.cursor()
        # we want to preserve the order of the authors, so do an update via SQL instead of using the built in set manipulators
        # FIXME: this will fail if you merge two authors of the same paper
        cursor.execute("update gPapers_paper_authors set author_id=%s where author_id=%s;", [self.id, id])
        other_author.delete()

    class Admin:
        list_display = ('id', 'name', 'location')

    def __unicode__(self):
        return self.name


class Sponsor(models.Model):

    name = models.CharField(max_length='1024')
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Admin:
        list_display = ('id', 'name',)

    def __unicode__(self):
        return self.name


class Paper(models.Model):

    title = models.CharField(max_length='1024')
    doi = models.CharField(max_length='1024', blank=True)
    pubmed_id = models.CharField(max_length='1024', blank=True)
    import_url = models.URLField(blank=True)
    source = models.ForeignKey(Source, null=True)
    source_session = models.CharField(max_length='1024', blank=True)
    source_pages = models.CharField(max_length='1024', blank=True)
    abstract = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    authors = models.ManyToManyField(Author)
    sponsors = models.ManyToManyField(Sponsor)
    organizations = models.ManyToManyField(Organization)
    full_text = models.FileField(upload_to=os.path.join('papers', '%Y', '%m'))
    full_text_md5 = models.CharField(max_length='32', blank=True)
    extracted_text = models.TextField(blank=True)
    page_count = models.IntegerField(default=0)
    rating = models.IntegerField(default=0)
    read_count = models.IntegerField(default=0)
    bibtex = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def save_file(self, filename, raw_contents, save=True):
        log_debug('Generating md5 sum')
        self.full_text_md5 = hashlib.md5(raw_contents).hexdigest()
        log_debug('Saving file content')
        self.full_text.save(filename,
                            django.core.files.base.ContentFile(raw_contents),
                            save)
        self.save()

    def get_authors_in_order(self):
        from django.db import connection
        cursor = connection.cursor()
        cursor.execute("select author_id from gPapers_paper_authors where paper_id=%s order by id;", [self.id])
        rows = cursor.fetchall()
        author_list = []
        for row in rows:
            author_list.append(Author.objects.get(id=row[0]))
        return author_list

    def open(self):
        if self.full_text and os.path.isfile(self.full_text.path):
            uri = 'file://' + self.full_text.path
            if Gtk.show_uri(None, uri, Gdk.CURRENT_TIME):
                self.read_count = self.read_count + 1
                self.save()
            else:
                log_error('Failed to open %s' % uri)

    class Admin:
        list_display = ('id', 'doi', 'title')

    def __unicode__(self):
        return 'Paper<%i: %s>' % (self.id, ' '.join([unicode(self.doi),
                                                     unicode(self.title),
                                                     unicode(self.authors.all())]))

    def pretty_string(self):
        return '[' + ', '.join([ author.name for author in self.get_authors_in_order() ]) + '] ' + self.title


class Reference(models.Model):

    referencing_paper = models.ForeignKey(Paper, null=True, blank=True)
    referenced_paper = models.ForeignKey(Paper, null=True, blank=True, related_name='citation_set')
    line_from_referencing_paper = models.CharField(max_length='1024', blank=True)
    line_from_referenced_paper = models.CharField(max_length='1024', blank=True)
    doi_from_referencing_paper = models.CharField(max_length='1024', blank=True)
    doi_from_referenced_paper = models.CharField(max_length='1024', blank=True)
    url_from_referencing_paper = models.URLField(blank=True)
    url_from_referenced_paper = models.URLField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Admin:
        list_display = ('id', 'referencing_paper', 'line_from_referencing_paper', 'doi_from_referencing_paper', 'referenced_paper', 'line_from_referenced_paper', 'doi_from_referenced_paper')

    def __unicode__(self):
        return 'Reference<%s,%s>' % (unicode(self.referencing_paper), unicode(self.referenced_paper))


class Bookmark(models.Model):

    paper = models.ForeignKey(Paper)
    page = models.IntegerField()
    x = models.FloatField(default=0.01)
    y = models.FloatField(default=0.01)
#    title = models.CharField(max_length='1024', blank=True)
    notes = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Admin:
        list_display = ('id', 'paper', 'page')

    def __unicode__(self):
        return self.notes


class Playlist(models.Model):

    title = models.CharField(max_length='1024', blank=True)
    search_text = models.CharField(max_length='1024', blank=True)
    parent = models.CharField(max_length=128)
    papers = models.ManyToManyField(Paper)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def get_papers_in_order(self):
        from django.db import connection
        cursor = connection.cursor()
        cursor.execute("select paper_id from gPapers_playlist_papers where playlist_id=%s order by id;", [self.id])
        rows = cursor.fetchall()
        paper_list = []
        for row in rows:
            paper_list.append(Paper.objects.get(id=row[0]))
        return paper_list

    class Admin:
        list_display = ('id', 'title', 'parent', 'search_text')

    def __unicode__(self):
        return self.title


###############################################################################
# "virtual" classes, used for non-existing papers, etc. to represent search
# results before they are imported
###############################################################################

class VirtualAuthor(object):

    def __init__(self, name):
        self.name = name


class VirtualSource(object):

    class SimpleDate(object):
        def __init__(self):
            self.year = None

    def __init__(self):
        self.name = None
        self.publication_date = VirtualSource.SimpleDate()


class VirtualPaper(object):
    ''' An object that can be treated for table display purposes as if it were
    an already existing :class:`Paper` object, i.e. it provides a title attribute etc.
    '''

    class VirtualSet(object):
        '''
        dummy class needed for faking the reference/citation relation
        '''
        @staticmethod
        def order_by(name):
            return []

    def __init__(self, paper_info, provider=None):
        '''
        Create a new object from the given dictionary `paper_info`
        '''

        self.id = -1
        self.paper_info = paper_info # save the complete info for later reuse
        self.provider = provider  # The origin of this search result
        self.authors = []
        self.source = VirtualSource()
        self.full_text = None
        self.abstract = None
        self.title = None
        self.created = datetime.today()
        self.reference_set = VirtualPaper.VirtualSet()
        self.citation_set = VirtualPaper.VirtualSet()
        self.bookmark_set = VirtualPaper.VirtualSet()
        self.notes = ''
        self.doi = None
        self.import_url = None
        self.pubmed_id = None

        for key in paper_info.keys():
            # take care of the more complex fields
            if key == 'authors':
                self.authors = [VirtualAuthor(author) for author in
                                paper_info['authors']]
            elif key == 'journal':
                self.source.name = paper_info['journal']
            elif key == 'year':
                self.source.publication_date.year = paper_info['year']
            else:
                self.__setattr__(key, paper_info[key])

    def get_authors_in_order(self):
        return self.authors
