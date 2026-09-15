# ycappuccino-client

Client navigateur (pyscript / Pyodide) pour un serveur `ycappuccino` exposé par `ycappuccino-http-server` : un client HTTP asynchrone pur Python parlant l'enveloppe `{"status", "meta", "data"}` et les routes `/api/crud/...`/`/api/services/...`, plus la preuve que les modèles `@Item` écrits pour le serveur (`ycappuccino.api.decorators`/`ycappuccino.api.models`) sont importables et utilisables tels quels côté client.

Conception : [docs/superpowers/specs/2026-09-15-client-design.md](docs/superpowers/specs/2026-09-15-client-design.md).

Prérequis : lire les README de [core](../core/README.md) (le constat qui justifie ce dépôt : `api`, `core.decorator_app` et `core.utils` "have no dependency, so decorators and models can be imported outside of the framework (e.g. by the pyscript client)"), d'[http_server](../http_server/README.md) (l'API que ce client consomme) et de [storage](../storage/README.md) (`@Item`, `@Property`, `get_storage_model()`).

## Mise en place

Ce dépôt n'est **pas** un `Host` en lui-même : ses assets navigateur (`static/`) sont destinés à être servis par un `Host` du dépôt [hosts](../hosts/README.md) (`Host.directory` pointant vers une copie de `client/static`). La partie testable en CPython (`ycappuccino.client.http`) s'installe comme les autres dépôts :

```bash
uv add --editable ../client
```

## Ce qui est partagé, et comment

### Constat empirique (§0 de la spec), pas une supposition

Sur cet interpréteur CPython (sans `pelix`/`iPOPO` installés), en ajoutant seulement `api/src/main/python` et `core/src/main/python` à `sys.path` :

| Clean (aucun `pelix`, ni direct ni transitif) | Non clean (importent réellement `pelix`) |
|---|---|
| `ycappuccino.api.core_base`, `ycappuccino.api.decorators`, `ycappuccino.api.models`, `ycappuccino.api.http`, `ycappuccino.api.proxy`, `ycappuccino.api.storage`, `ycappuccino.api.endpoints_storage`, `ycappuccino.api.endpoints_service`, `ycappuccino.api.http_server`, `ycappuccino.core.utils`, `ycappuccino.core.decorator_app` | `ycappuccino.api.component_creator` (`from pelix.ipopo.decorators import Property`), `ycappuccino.core.framework`, `ycappuccino.core.runner` |

C'est plus large que ce que l'énoncé de ce sous-projet supposait : `ycappuccino.api.storage` (le port `IManager`/`ITrigger`/`IFilter`) est clean aussi. Détails, méthode et limites dans la spec §0.

**Autre constat, décisif pour l'emballage** : `api/pyproject.toml` déclare `iPOPO>=3.0` sans condition. `uv add --editable ../api` installe donc réellement `iPOPO`+`jsonrpclib-pelix`, même si les modules ci-dessus n'en ont pas besoin à l'exécution — la déclaration de dépendance d'un paquet n'est pas son graphe d'import réel. Ce dépôt déclare quand même `ycappuccino-api`/`ycappuccino-core` en dépendances `uv` normales (comme `storage`, `http_server`...) : c'est sans conséquence pour le `.venv` de développement (jamais expédié au navigateur), mais **le bootstrap navigateur ne doit jamais reproduire ce chemin d'installation** : il doit utiliser `micropip.install(url, deps=False)` pour ne récupérer que le code, jamais la résolution de `iPOPO`. Voir spec §0/§4.

### Conséquence : un module de modèles applicatif est réutilisable tel quel

Un fichier comme `example/library/books.py` (ci-dessous), qui n'importe que `ycappuccino.api.decorators`/`ycappuccino.api.models`, est exactement le fichier qu'un développeur écrirait pour son serveur `ycappuccino-storage` — et il est importable côté client sans changement.

## Exemple

```python
from ycappuccino.client.http import ApiClient

client = ApiClient("http://localhost:9000", token="demo")   # token optionnel, envoyé en Authorization: Bearer ...

document = await client.get_one("books", "dune")
await client.get_many("books", {"filter": {"pages": {"$gte": 400}}, "sort": {"title": 1}})
await client.create("books", {"title": "Dune", "pages": 412})
await client.update("books", "dune", {"pages": 412})
await client.delete("books", "dune")
await client.delete_many("books", {"pages": {"$lt": 100}})
await client.call("echo", "POST", body={"hello": "world"})
```

Les méthodes reflètent volontairement `ycappuccino.api.endpoints_storage.ICrud` et `ycappuccino.api.endpoints_service.IServiceEndpoint` (mêmes noms, même ordre de paramètres, sans `subject` : c'est le serveur qui le déduit des en-têtes HTTP). Les échecs HTTP (401/403/404/400/autre) lèvent les **mêmes classes** que côté serveur : `NotAuthenticated`, `Forbidden`, `NotFound`, `InvalidRequest`, `CrudError` (`ycappuccino.api.endpoints_storage`).

### Modèle partagé, round-trip complet

```python
from library.books import Book   # example/library/books.py

document = await client.get_one("books", "dune")   # dict brut, tel que renvoyé par le serveur
book = Book(document)
book.on_read(False)                                 # même séquence que ycappuccino.storage.manager.Manager.get_one
book.get_storage_model()                            # {"_id": "dune", "title": "Dune", "pages": 412}
```

## Transport : `pyodide.http.pyfetch`, avec repli explicite

`ApiClient` n'importe jamais `pyodide` au niveau module (sinon le paquet ne serait pas testable en CPython). Sans transport injecté, il utilise `ycappuccino.client.pyodide_transport.pyodide_transport`, qui importe `pyodide.http` à l'intérieur de la fonction : hors Pyodide, l'appel lève un `RuntimeError` explicite plutôt qu'un `ModuleNotFoundError` muet. Pour les tests, on injecte un transport falsifié :

```python
async def fake_transport(method, url, headers, body):
    ...
    return RawResponse(status=200, headers={}, body=b'{"status":200,"meta":{"type":"object","size":1},"data":{"_id":"dune"}}')

client = ApiClient("http://api", transport=fake_transport)
```

## Limites et vérifications manuelles requises

Rien de ce qui touche un vrai navigateur n'a pu être exécuté dans l'environnement qui a produit ce dépôt (pas de réseau pour charger Pyodide/pyscript depuis un CDN). Précisément, **ne sont pas prouvés ici, et nécessitent une vérification manuelle en navigateur avant mise en production** :

- Le comportement réel de `pyodide.http.pyfetch` (`ycappuccino/client/pyodide_transport.py`) : noms exacts des options, forme de `FetchResponse`, gestion des cookies/CORS/`credentials`.
- Que `static/index.html`/`static/main.py` fonctionnent réellement : que le CDN pyscript épinglé (`https://pyscript.net/releases/2024.11.1/`) existe encore et répond, que l'API `pyscript`/`js` utilisée est bien celle de cette version, que le fetch de `/api/items` aboutit face à un vrai `http_server` (same-origin ou CORS).
- Que `micropip.install(url, deps=False)` se comporte comme documenté sur la version de Pyodide réellement chargée, et que les modules clean identifiés ci-dessus s'exécutent sans surprise sous Wasm (aucune raison connue d'en douter : ce sont des modules Python purs, stdlib uniquement, mais ce n'est pas *prouvé* par ce qui a été exécuté ici).
- La construction réelle des wheels `ycappuccino-api`/`ycappuccino-core`/`ycappuccino-client` et leur mise à disposition par un `Host` : non faite ici (hors périmètre, aucun réseau/index de paquets réel).

Ce qui **est** prouvé (par exécution réelle, dans ce bac à sable) : le graphe d'import exact d'`api`/`core` (§0), et le comportement de `ApiClient` (encodage des requêtes, décodage de l'enveloppe, mapping des erreurs) ainsi que le round-trip `document -> Book -> get_storage_model()`, les deux via `unittest` en CPython pur, avec un transport HTTP falsifié.

## Développer client

```bash
uv sync
uv run python -m unittest discover -s src/unittest/python
```

`static/` n'est pas exécuté par cette commande : ce sont des assets navigateur, pas du code Python testable en CPython.
