# ycappuccino-client

Le vrai `ycappuccino.core.framework.Framework` (Pelix/iPOPO) dans un navigateur, via Pyodide. Le code
applicatif y est écrit comme sur un backend : un composant natif dépend des **interfaces** backend
(`ILoginService`, `ICrud`, n'importe quelle interface publique), et le framework lui injecte des
**proxies générés par réflexion** qui appellent le backend en JSON-RPC. Rien, dans le code applicatif, ne
sait que l'implémentation est de l'autre côté de HTTP.

Le client est une instance YCappuccino comme les autres : il utilise le même mécanisme que les appels
entre backends de [`remote`](../remote/README.md) (`__remote_dispatch__`), avec l'utilisateur connecté comme
appelant. Conception : `remote/docs/superpowers/specs/2026-09-16-transparent-rpc-design.md`, section 11.

**Risque assumé, à lire avant le reste : « Risques d'exécution navigateur » plus bas.** Rien de ce qui
touche un vrai navigateur n'a pu être vérifié dans l'environnement qui a produit ce dépôt.

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

Séquence, jamais exécutée dans un vrai navigateur ici :

1. Charger un build Pyodide **pthread**, page servie avec `Cross-Origin-Opener-Policy: same-origin` et
   `Cross-Origin-Embedder-Policy: require-corp` (risque (a)).
2. `pyodide.loadPackage("pyyaml")` (risque (b)).
3. `micropip.install(url, deps=False)` pour `iPOPO`, `ycappuccino-api`, `ycappuccino-core`,
   `ycappuccino-client`, puis les wheels de l'application.
4. Écrire `conf/application.yml` dans le système de fichiers virtuel de Pyodide (risque (c)).
5. `discovery.prepare_generated_module("bundle/generated_remote.py")`.
6. `Framework().init("conf/application.yml")`, puis lire les composants de l'application.

## Risques d'exécution navigateur

**(a) Threads réels.** `core.async_runner.AsyncRunner` fait tourner une boucle asyncio sur un vrai thread
OS : c'est ce qui démarre chaque composant natif. Un build Pyodide mono-thread ne peut pas en démarrer ;
il faut un build pthread (threads WebAssembly via `SharedArrayBuffer`), donc une page servie avec les
deux en-têtes COOP/COEP (`Host.cross_origin_isolated` dans `hosts`). Non vérifié : qu'un CDN public
fournisse ce build, et qu'il fonctionne réellement.

**(b) PyYAML.** `Framework.init()` lit l'`application.yml` avec PyYAML, chargé par le chargeur curaté de
Pyodide. Non vérifié : sa présence dans la liste curatée de la version chargée.

**(c) Chemin de fichier.** `Framework.init(yml_path)` veut un vrai fichier : le bootstrap l'écrit dans le
système de fichiers virtuel de Pyodide.

**(d) `Set-Cookie` illisible.** `fetch()` n'expose jamais `Set-Cookie`. Le jeton vient donc du résultat de
`ILoginService.login()`, jamais d'un cookie.

**(e) COOP/COEP et CDN tiers.** Ces en-têtes peuvent empêcher de charger Pyodide depuis un CDN qui n'envoie
pas d'en-têtes CORP/CORS compatibles.

## Ce qui est prouvé, ce qui ne l'est pas

Prouvé par `test_client_framework.py`, exécuté en CPython : un vrai backend en sous-processus
(`http_server`, `endpoints_*`, `permissions_app`, `remote.dispatch`/`capabilities`), un vrai `Framework`
client qui découvre ses interfaces publiques, génère et installe les proxies, injecte `ILoginService`/
`ICrud`/`ISession` dans un composant applicatif, se connecte, écrit et relit avec les droits de
l'utilisateur, se voit refuser une lecture anonyme et une interface interne. Seul
`pyodide_transport` y est remplacé par un fetch `urllib` équivalent.

Non prouvé, à vérifier en navigateur avant toute mise en production : les risques (a), (b), (e) ;
`pyodide.http.pyfetch` réel (noms d'options, forme de la réponse) ; iPOPO sous Pyodide ; `static/` ; la
construction et la mise à disposition des wheels.

## Développer client

```bash
uv sync
uv run python -m unittest discover -s src/unittest/python
```

Le groupe de dépendances `dev` installe les repos backend nécessaires au test de bout en bout.
