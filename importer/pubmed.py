import urllib

import BeautifulSoup

from gPapers.models import *

BASE_URL = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
ESEARCH_QUERY = 'esearch.fcgi?db=pubmed&term=%s&usehistory=y'
ESUMMARY_QUERY = 'esummary.fcgi?db=pubmed&query_key=%s&WebEnv=%s'

def search(search_text):
    '''
    Returns a list of dictionaries: The PUBMED results for the given search
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
        info = {}
        # Extract information
        info['pubmed_id'] = str(document.id.string)        

        doi = document.findAll('item', {'name' : 'doi'})
        import_url = ''
        if doi:
            info['doi'] = doi[0].string
            info['import_url'] = 'http://dx.doi.org/' + info['doi']
            
        info['title'] = document.findAll('item', {'name' : 'Title'})[0].string
        info['authors'] = [str(author.string) for author in \
                                  document.findAll('item', {'name' : 'Author'})]            
        info['journal'] = document.findAll('item',
                                          {'name' : 'FullJournalName'})[0].string
                                            
        pubdate = document.findAll('item', {'name' : 'PubDate'})
        if pubdate and pubdate[0]:
            info['year'] = pubdate[0].string[:4]
        
        #TODO: Retrieve abstract
        abstract = ''

        paper = Paper(doi=doi, pubmed_id=pubmed_id, import_url=import_url,
                      title=title, source=source)
        author_list = []
        for author in authors:
            try:
                author_obj = Author.objects.get(name=author.string)
            except Author.DoesNotExist:
                author_obj = Author(name=author.string)
            author_list.append(author_obj)
            
        papers.append(info)

    return papers
        