"""FakeItemCatalog: minimal IItemCatalog double for RemoteCrud/RemoteDrafts unit tests - only
get_item (item_id -> plural resolution) is exercised, the rest raise if ever called by mistake."""

from ycappuccino.api.endpoints_storage import IItemCatalog


class FakeItemCatalog(IItemCatalog):
    def __init__(self, plural_by_id):
        self._plural_by_id = plural_by_id

    async def start(self):
        pass

    async def stop(self):
        pass

    async def get_item(self, item_id, subject=None):
        return {"id": item_id, "plural": self._plural_by_id[item_id]}

    async def get_items(self, subject=None):
        raise NotImplementedError

    async def get_item_by_plural(self, plural, subject=None):
        raise NotImplementedError

    async def get_schema(self, item_id, subject=None):
        raise NotImplementedError

    async def get_empty(self, item_id, subject=None):
        raise NotImplementedError
