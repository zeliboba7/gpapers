The Django model
================

.. currentmodule:: gpapers.gPapers.models

The model objects represent the corresponding tables in the database.

.. autoclass:: Publisher
   :members:

.. autoclass:: Source
   :members:

.. autoclass:: Organization
   :members:

.. autoclass:: Author
   :members:

.. autoclass:: Sponsor
   :members:

.. autoclass:: Paper
   :members:

.. autoclass:: Reference
   :members:
   
.. autoclass:: Bookmark
   :members:

.. autoclass:: Playlist
   :members:

"Virtual models"
----------------
These objects are simple dummy classes that can be used for search results which
do not yet have an equivalent in the database.

.. autoclass:: VirtualPaper
   :members:

.. autoclass:: VirtualAuthor
   :members:

.. autoclass:: VirtualSource
   :members:



