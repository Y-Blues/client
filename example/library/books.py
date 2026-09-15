"""
Example: an @Item model, shared as-is between a ycappuccino-storage server and this pyscript
client. Structurally the same file an application author would write for the server (compare
storage/example/library/books.py), it only imports ycappuccino.api.decorators and
ycappuccino.api.models - the import-clean subset identified in
client/docs/superpowers/specs/2026-09-15-client-design.md §0 - never ycappuccino.storage,
ycappuccino.core, nor Pelix. That is what makes it importable client-side, under Pyodide, without
adaptation.
"""

from ycappuccino.api.decorators import Item, Property
from ycappuccino.api.models import Model


@Item(collection="books", name="book", plural="books")
class Book(Model):

    def __init__(self, a_dict=None):
        super().__init__(a_dict)
        self._title = None
        self._pages = None

    @Property(name="title")
    def title(self, a_value):
        self._title = a_value

    @Property(name="pages", type="integer", minimum=0)
    def pages(self, a_value):
        self._pages = a_value
