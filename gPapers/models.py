from django.db import models


class Publisher(models.Model):

    name = models.CharField(max_length='1024')

    class Admin:
        list_display = ( 'name', )

    def __unicode__(self):
        return self.name

    
class Source(models.Model):

    name = models.CharField(max_length='1024')
    issue = models.CharField(max_length='1024')
    acm_toc_url = models.URLField()
    location = models.CharField(max_length='1024')
    publication_date = models.DateField()
    publisher = models.ForeignKey(Publisher, null=True)

    class Admin:
        list_display = ( 'id', 'name', 'issue', 'location', 'publisher', 'publication_date', )


class Author(models.Model):

    name = models.CharField(max_length='1024')
    location = models.CharField(max_length='1024')
    organization = models.CharField(max_length='1024')
    department = models.CharField(max_length='1024')

    class Admin:
        list_display = ( 'name', 'location', 'organization', 'department' )

    def __unicode__(self):
        return self.name
    
    
class Sponsor(models.Model):

    name = models.CharField(max_length='1024')

    class Admin:
        list_display = ( 'id', 'name', )

    def __unicode__(self):
        return self.name
    
    
class Reference(models.Model):

    line = models.CharField(max_length='1024')
    doi = models.CharField(max_length='1024', blank=True)
    ieee_url = models.URLField()

    class Admin:
        list_display = ( 'id', 'line', 'doi' )

    def __unicode__(self):
        return self.line


class Paper(models.Model):
    
    title = models.CharField(max_length='1024')
    doi = models.CharField(max_length='1024')
    source = models.ForeignKey(Source, null=True)
    source_session = models.CharField(max_length='1024')
    source_pages = models.CharField(max_length='1024')
    abstract = models.TextField()
    authors = models.ManyToManyField(Author)
    sponsors = models.ManyToManyField(Sponsor)
    references = models.ManyToManyField(Reference)
    
    class Admin:
        list_display = ( 'doi', 'title' )


