import urllib

import BeautifulSoup

from gPapers.models import *

BASE_URL = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
ESEARCH_QUERY = 'esearch.fcgi?db=pubmed&term=%s&usehistory=y'
ESUMMARY_QUERY = 'esummary.fcgi?db=pubmed&query_key=%s&WebEnv=%s'

def search(search_text):
    '''
    Returns a list of Paper objects: The PUBMED results for the given search
    query
    '''

    if not search_text:
        return [] # Do not make empty queries

    # First do a query only for ids that is saved on the server
    query = BASE_URL + ESEARCH_QUERY % urllib.quote_plus(search_text)
    response = urllib.urlopen(query)
    if not (response.getcode() == 200 or response.getcode() == 302):
        #TODO: Show a dialog or handle it differently?
        return []
                    
    parsed_response = BeautifulSoup.BeautifulStoneSoup(response)
    
    # Check wether there were any hits at all
    if int(parsed_response.esearchresult.count.string) == 0:
        return []
    
    web_env = parsed_response.esearchresult.webenv.string
    query_key = parsed_response.esearchresult.querykey.string
    response.close()
    
    # Download the summaries
    query = BASE_URL + ESUMMARY_QUERY % (query_key, web_env)
    response = urllib.urlopen(query)
    if not (response.getcode() == 200 or response.getcode() == 302):        
        return []           
    parsed_response = BeautifulSoup.BeautifulStoneSoup(response)

    # get information for all documents
    documents = parsed_response.esummaryresult.findAll('docsum') 
    papers = []
    for document in documents:    
        # Extract information
        pubmed_id = document.id.string        
        doi = document.findAll('item', {'name' : 'doi'})
        import_url = ''
        if doi:
            doi = doi[0].string
            import_url = 'http://dx.doi.org/' + doi
        title = document.findAll('item', {'name' : 'Title'})[0].string
        authors = document.findAll('item', {'name' : 'Author'})
            
        journal = document.findAll('item',
                                   {'name' : 'FullJournalName'})[0].string

        #TODO: How to handle publication date?                                    
        #pubdate = document.findAll('item', {'name' : 'PubDate'})[0]                                   

        try:
            source = Source.objects.get(name=journal)
        except Source.DoesNotExist:
            source = Source(name=journal)
        
        
        #TODO: Retrieve abstract
        abstract = ''

        paper = Paper(doi=doi, pubmed_id=pubmed_id, import_url=import_url,
                      title=title, source=source)
        for author in authors:
            try:
                author_obj = Author.objects.get(name=author.string)
            except Author.DoesNotExist:
                author_obj = Author(name=author.string)
            #FIXME: This does not work for not yet existing papers
            paper.authors.add(author_obj)
            
        papers.append(paper)

    return papers
        