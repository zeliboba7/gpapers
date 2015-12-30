This page only contains instructions for Ubuntu 12.04 at the moment, but the installation should be similar on other Linuxes offering recent libraries.

# Ubuntu 12.04 #
## Install dependencies ##
```
sudo apt-get install gir1.2-gtk-3.0 gir1.2-poppler-0.18 gir1.2-soup-2.4 python-django python-pdfminer python-beautifulsoup python-pyparsing python-feedparser
```

## Install gPapers from the repository ##
  1. Install mercurial: `sudo apt-get install mercurial`
  1. Clone repository: `hg clone https://code.google.com/p/gpapers/`
  1. Install gPapers: `cd gpapers; sudo python setup.py install`

gPapers should now be available via the `gpapers` command and in the Unity dash.