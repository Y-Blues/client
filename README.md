# ycappuccino-client

Le vrai `ycappuccino.core.framework.Framework` (Pelix/iPOPO) dans un navigateur, via Pyodide. Le code
applicatif y est écrit comme sur un backend : un composant natif dépend des **interfaces** backend
(`ILoginService`, `ICrud`, n'importe quelle interface publique), et le framework lui injecte des
**proxies générés par réflexion** qui appellent le backend en JSON-RPC. Rien, dans le code applicatif, ne
sait que l'implémentation est de l'autre côté de HTTP.

Le client est une instance YCappuccino comme les autres : il utilise le même mécanisme que les appels
entre backends de [`remote`](../remote/README.md) (`__remote_dispatch__`), avec l'utilisateur connecté comme
appelant. Conception : `remote/docs/superpowers/specs/2026-09-16-transparent-rpc-design.md`, section 11.

## Ce que le code applicatif écrit

```python
from ycappuccino.api.core_base import YCappuccinoComponent
from ycappuccino.api.endpoints_storage import ICrud
from ycappuccino.api.permissions import ILoginService
from ycappuccino.client.transport import ISession


class Account(YCappuccinoComponent):

    def __init__(self, login: ILoginService, crud: ICrud, session: ISession):
        self._login = login
        self._crud = crud
        self._session = session

    async def start(self):
        pass

    async def stop(self):
        pass

    async def sign_in(self, login: str, password: str) -> None:
        self._session.set_token(await self._login.login(login, password))

    async def organization(self, id: str) -> dict:
        return await self._crud.get_one("organization", id)
```

`ISession` est le seul service propre au client que le code applicatif nomme : il porte le jeton de
l'utilisateur connecté, envoyé en `Authorization: Bearer` sur chaque appel suivant. Le client n'envoie
jamais de `subject` : le backend le déduit du jeton. Un paramètre `subject` d'une méthode d'interface est
accepté par le proxy (même signature que côté serveur) mais jamais transmis.

## Les proxies

`ycappuccino.client.rpc_proxy.make_rpc_proxy(interface, qualified_path)` synthétise une classe
`Remote<Nom>` qui implémente toutes les méthodes abstraites de l'interface. Chaque appel devient :

```
POST /api/services/__remote_dispatch__/<chemin qualifié>/<méthode>   {"kwargs": {...}}
```

reçu par `ycappuccino.remote.dispatch.RemoteDispatch` sur le backend. Arguments et résultats sont en JSON ;
un résultat annoté par une dataclass (`ServiceResult`, par exemple) est reconstruit. Une erreur du backend
revient comme la même erreur locale : `NotAuthenticated` (401), `Forbidden` (403), `NotFound` (404),
`InvalidRequest` (400), `CrudError` sinon.

Seules les méthodes `@rpc_method` d'une interface sont appelables depuis un navigateur (voir `remote`,
« Sécurité : deux niveaux d'accès ») ; une méthode `secure=True` exige en plus un utilisateur autorisé à
`call` `<chemin qualifié>.<méthode>`.

## Découverte, avant le démarrage du framework

Le bootstrap demande au backend ses interfaces publiques **avant** `Framework().init()` et écrit un module
Python ordinaire qui déclare un proxy par interface :

```python
from ycappuccino.client import discovery

paths = await discovery.prepare_generated_module("bundle/generated_remote.py")
```

```python
# bundle/generated_remote.py, généré
from ycappuccino.api.endpoints_storage import ICrud
from ycappuccino.api.permissions import ILoginService
from ycappuccino.client.rpc_proxy import make_rpc_proxy

RemoteCrud = make_rpc_proxy(ICrud, 'ycappuccino.api.endpoints_storage.ICrud')
RemoteLoginService = make_rpc_proxy(ILoginService, 'ycappuccino.api.permissions.ILoginService')
```

Le scan `bundle_prefix` normal installe ce module comme du code écrit à la main : les proxies existent
avant qu'un composant qui en dépend soit validé, donc une dépendance vers une interface backend peut être
requise (contrairement aux proxies d'un backend pair, créés après coup). `bundle_prefix` liste alors
`ycappuccino.client.transport`, puis le module généré, puis l'application.

Si le backend ne peut pas être interrogé (pas de `ycappuccino.remote.capabilities`, erreur réseau, réponse
invalide), le client proxie `ICrud`, `IDrafts`, `IItemCatalog` et `IServiceEndpoint`
(`known_interfaces.FALLBACK_INTERFACES`). Lister simplement `ycappuccino.client` dans `bundle_prefix`
installe ces quatre proxies sans découverte.

Une interface découverte doit être importable dans le navigateur (son module fait partie des wheels
chargées) : un proxy est une classe Python qui en hérite.

## Côté backend

Le backend doit charger, en plus de `http_server` et de ses use cases, les modules suivants de
`ycappuccino.remote` (listés un par un : le paquet entier fournirait un second `IServiceEndpoint`) :

```yaml
bundle_prefix:
  - ycappuccino.storage
  - ycappuccino.endpoints_storage
  - ycappuccino.endpoints_service
  - ycappuccino.http_server
  - ycappuccino.permissions          # JwtAuthentication, ILoginService, IAuthorization
  - ycappuccino.remote.dispatch
  - ycappuccino.remote.capabilities
```

## Transport bas niveau

`HttpTransport` (`ycappuccino.client.transport`) implémente `ISession` et porte l'URL de base (`/api` par
défaut, même origine que la page ; surchargeable par la clé `client.base_url` de
`conf/config.properties`, lue au `start()`). Il délègue le fetch à un `IHttpFetcher` s'il en reçoit un,
sinon à `ycappuccino.client.pyodide_transport.pyodide_transport`, qui importe `pyodide.http` à l'appel
seulement : hors Pyodide, il lève un `RuntimeError` explicite.

## Modèle partagé

`example/library/books.py` est un modèle `@Item` ordinaire, importable des deux côtés :

```python
from library.books import Book

book = Book({"_id": "dune", "title": "Dune", "pages": 412})
book.on_read(False)
book.get_storage_model()  # {"_id": "dune", "title": "Dune", "pages": 412}
```

## Bootstrap navigateur : `static/index.html` + `static/main.py`

Séquence :

1. Charger Pyodide (build standard, aucun en-tête particulier requis).
2. `pyodide.loadPackage(["micropip", "pyyaml"])`.
3. `micropip.install("iPOPO>=3.0")`, puis `micropip.install(url, deps=False)` pour `ycappuccino-api`,
   `ycappuccino-core`, `ycappuccino-client` et les wheels de l'application.
4. Écrire `conf/application.yml` dans le système de fichiers virtuel de Pyodide (`Framework.init` veut un
   vrai chemin).
5. `discovery.prepare_generated_module("bundle/generated_remote.py")`, puis `sys.path.insert(0, "bundle")`.
6. `Framework().init("conf/application.yml")`, puis lire les composants de l'application.

## Vérifié dans un vrai navigateur (2026-09-17)

Chromium piloté par Playwright, Pyodide 0.28.3 (Python 3.13) depuis jsDelivr, page et `/api` servis par la
même origine devant un vrai backend (`http_server`, `endpoints_*`, `permissions_app`,
`remote.dispatch`/`capabilities`) :

- iPOPO s'installe par micropip, le `Framework` démarre, les composants natifs sont validés et publiés ;
- la découverte passe par le vrai `pyodide_transport` (`pyfetch`) et génère un proxy par interface publique ;
- un composant qui dépend d'`ILoginService`, `ICrud` et `ISession` est injecté ; une lecture anonyme lève
  `NotAuthenticated`, `ILoginService.login()` rend un jeton, les appels suivants passent authentifiés.

Pyodide ne peut démarrer aucun thread : `core.async_runner.AsyncRunner` exécute alors les coroutines des
composants sur le thread appelant (voir le README de `core`), sans build pthread ni en-têtes COOP/COEP.

Restent non vérifiés : `static/` tel quel (la vérification a utilisé une page équivalente), Firefox et
Safari, et la construction et la mise à disposition des wheels par `hosts`.

**`Set-Cookie` illisible.** `fetch()` n'expose jamais `Set-Cookie` : le jeton vient du résultat de
`ILoginService.login()`, jamais d'un cookie.

## Tests

`test_client_framework.py`, en CPython : même scénario contre un vrai backend en sous-processus, avec un
fetch `urllib` à la place de `pyodide_transport`.

## Développer client

```bash
uv sync
uv run python -m unittest discover -s src/unittest/python
```

Le groupe de dépendances `dev` installe les repos backend nécessaires au test de bout en bout.
