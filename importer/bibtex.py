# coding: utf8
import re
from logger import log_info, log_debug
import pprint
""" Pyparsing parser for BibTeX files

A standalone parser using pyparsing.

pyparsing has a simple and expressive syntax so the grammar is easy to read and
write.

Matthew Brett 2010
Simplified BSD license
"""

from pyparsing import (Regex, Suppress, ZeroOrMore, Group, Optional, Forward,
                       SkipTo, CaselessLiteral, Dict)


class Macro(object):
    """ Class to encapsulate undefined macro references """
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return 'Macro("%s")' % self.name
    def __eq__(self, other):
        return self.name == other.name
    def __ne__(self, other):
        return self.name != other.name


# Character literals
LCURLY = Suppress('{')
RCURLY = Suppress('}')
LPAREN = Suppress('(')
RPAREN = Suppress(')')
QUOTE = Suppress('"')
COMMA = Suppress(',')
AT = Suppress('@')
EQUALS = Suppress('=')
HASH = Suppress('#')


def bracketed(expr):
    """ Return matcher for `expr` between curly brackets or parentheses """
    return (LPAREN + expr + RPAREN) | (LCURLY + expr + RCURLY)


# Define parser components for strings (the hard bit)
chars_no_curly = Regex(r"[^{}]+")
chars_no_curly.leaveWhitespace()
chars_no_quotecurly = Regex(r'[^"{}]+')
chars_no_quotecurly.leaveWhitespace()
# Curly string is some stuff without curlies, or nested curly sequences
curly_string = Forward()
curly_item = Group(curly_string) | chars_no_curly
curly_string << LCURLY + ZeroOrMore(curly_item) + RCURLY
# quoted string is either just stuff within quotes, or stuff within quotes, within
# which there is nested curliness
quoted_item = Group(curly_string) | chars_no_quotecurly
quoted_string = QUOTE + ZeroOrMore(quoted_item) + QUOTE

# Numbers can just be numbers. Only integers though.
number = Regex('[0-9]+')

# Basis characters (by exclusion) for variable / field names.  The following
# list of characters is from the btparse documentation
any_name = Regex('[^\s"#%\'(),={}]+')

# btparse says, and the test bibs show by experiment, that macro and field names
# cannot start with a digit.  In fact entry type names cannot start with a digit
# either (see tests/bibs). Cite keys can start with a digit
not_digname = Regex('[^\d\s"#%\'(),={}][^\s"#%\'(),={}]*')

# Comment comments out to end of line
comment = (AT + CaselessLiteral('comment') +
           Regex("[\s{(].*").leaveWhitespace())

# The name types with their digiteyness
not_dig_lower = not_digname.copy().setParseAction(
    lambda t: t[0].lower())
macro_def = not_dig_lower.copy()
macro_ref = not_dig_lower.copy().setParseAction(lambda t : Macro(t[0].lower()))
field_name = not_dig_lower.copy()
# Spaces in names mean they cannot clash with field names
entry_type = not_dig_lower.setResultsName('entry type')
cite_key = any_name.setResultsName('cite key')
# Number has to be before macro name
string = (number | macro_ref | quoted_string |
          curly_string)

# There can be hash concatenation
field_value = string + ZeroOrMore(HASH + string)
field_def = Group(field_name + EQUALS + field_value)
entry_contents = Dict(ZeroOrMore(field_def + COMMA) + Optional(field_def))

# Entry is surrounded either by parentheses or curlies
entry = (AT + entry_type +
         bracketed(cite_key + COMMA + entry_contents))

# Preamble is a macro-like thing with no name
preamble = AT + CaselessLiteral('preamble') + bracketed(field_value)

# Macros (aka strings)
macro_contents = macro_def + EQUALS + field_value
macro = AT + CaselessLiteral('string') + bracketed(macro_contents)

# Implicit comments
icomment = SkipTo('@').setParseAction(lambda t : t.insert(0, 'icomment'))

# entries are last in the list (other than the fallback) because they have
# arbitrary start patterns that would match comments, preamble or macro
definitions = Group(comment |
                    preamble |
                    macro |
                    entry |
                    icomment)

# Start symbol
bibfile = ZeroOrMore(definitions)


def parse_str(str):
    return bibfile.parseString(str)

if __name__ == '__main__':
    # Run basic test
    txt = """
@article{10.1371/journal.pone.0020409,
    author = {Tkačik, Gašper AND Garrigan, Patrick AND Ratliff, Charles AND Milčinski, Grega AND Klein, Jennifer M. AND Seyfarth, Lucia H. AND Sterling, Peter AND Brainard, David H. AND Balasubramanian, Vijay},
    journal = {PLoS ONE},
    publisher = {Public Library of Science},
    title = {Natural {I}mages from the Birthplace of the Human Eye},
    year = {2011},
    month = {06},
    volume = {6},
    url = {http://dx.doi.org/10.1371%2Fjournal.pone.0020409},
    pages = {e20409},
    abstract = {
        <p>Here we introduce a database of calibrated natural images publicly available through an easy-to-use web interface. Using a Nikon D70 digital SLR camera, we acquired about <inline-formula><inline-graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="info:doi/10.1371/journal.pone.0020409.e001" mimetype="image" xlink:type="simple"/></inline-formula> six-megapixel images of Okavango Delta of Botswana, a tropical savanna habitat similar to where the human eye is thought to have evolved. Some sequences of images were captured unsystematically while following a baboon troop, while others were designed to vary a single parameter such as aperture, object distance, time of day or position on the horizon. Images are available in the raw RGB format and in grayscale. Images are also available in units relevant to the physiology of human cone photoreceptors, where pixel values represent the expected number of photoisomerizations per second for cones sensitive to long (L), medium (M) and short (S) wavelengths. This database is distributed under a Creative Commons Attribution-Noncommercial Unported license to facilitate research in computer vision, psychophysics of perception, and visual neuroscience.</p>
      },
    number = {6},
    doi = {10.1371/journal.pone.0020409}
}        
"""
    pp = pprint.PrettyPrinter(indent=4)

    pp.pprint(mydict)

p_bibtex = re.compile('[@][a-z]+[\s]*{(.*)}', re.IGNORECASE | re.DOTALL)

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
    return s


def paper_info_from_bibtex(data):

    # ieee puts <br>s in their bibtex
    data = data.replace('<br>', '\n')

    paper_info = {}

    result = parse_str(data)
    bibtex = {}
    # FIXME: This does not handle special cases well...
    for i, r in enumerate(result[0][2:]):
        bibtex[r[0].lower()] = ''.join([str(r_part) for r_part in r[1:]])

    # fix for ACM's doi retardedness
    if bibtex.get('doi', '').startswith('http://dx.doi.org/'):
        bibtex['doi'] = bibtex['doi'][ len('http://dx.doi.org/'): ]
    if bibtex.get('doi', '').startswith('http://doi.acm.org/'):
        bibtex['doi'] = bibtex['doi'][ len('http://doi.acm.org/'): ]

    # Mappings from BibTeX to our keys
    # TODO: Handle more fields
    mappings = {'doi': 'doi',
                'url': 'import_url',
                'title': 'title',
                'pages': 'pages',
                'abstract': 'abstract',
                'journal': 'journal',
                'year': 'year',
                'publisher': 'publisher'}

    for bibtex_key, our_key in mappings.items():
        if bibtex_key in bibtex:
            log_debug('Have key %s' % bibtex_key)
            paper_info[our_key] = bibtex[bibtex_key]

    # TODO: Handle editors, etc.?
    if 'author' in bibtex:
        if ' AND ' in bibtex['author']:
            paper_info['authors'] = bibtex['author'].split(' AND ')
        else:
            paper_info['authors'] = bibtex['author'].split(' and ')

    paper_info['bibtex'] = data
    log_info('imported paper_info: %s\nFrom bibtex: %s' % (str(paper_info), str(bibtex)))

    return paper_info
