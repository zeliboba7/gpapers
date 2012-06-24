# coding: utf8

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
#
# This file is based on code by Matthew Brett (http://pastebin.com/ZzU19NLJ),
# published under a simplified BSD license.

# -- begin of pyparsing code
#  Pyparsing parser for BibTeX files
#
#  A standalone parser using pyparsing.
#
#  pyparsing has a simple and expressive syntax so the grammar is easy to read and
#  write.
#
#  Matthew Brett 2010
#  Simplified BSD license

from gpapers.logger import log_info, log_debug

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

# -- end of pyparsing code

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
    
    if data is None:
        return {}

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
