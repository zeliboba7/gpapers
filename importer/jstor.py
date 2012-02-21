class JSTORSearch(object):

    def __init__(self):
        self.name = 'JSTOR'
        self.label = 'jstor'
        self.icon = 'favicon_jstor.ico'
        self.search_cache = {}

    def clear_cache(self, text):
        if text in self.search_cache:
            del self.search_cache[text]

    def search(self, search_text):
        return [] #Not implemented yet
