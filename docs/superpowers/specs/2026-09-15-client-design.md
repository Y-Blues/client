# client pyscript : design

Date : 2026-09-15. Nouveau sous-projet de l'écosystème YCappuccino : un client navigateur (pyscript / Pyodide) qui parle à un `ycappuccino` serveur exposé par `http_server`, en réutilisant si possible le code Python partagé (`api`, `core.decorator_app`, `core.utils`).

Dépôt greffé sans code legacy (greenfield), mais qui doit suivre les conventions des dépôts voisins (`uv_build`, `src/main/python` / `src/unittest/python`, tests `unittest`, README en français, specs/plans `docs/superpowers`).

## 0. Validation empirique de l'hypothèse centrale

**Hypothèse à vérifier avant tout design** (`core/src/main/python/ycappuccino/core/utils.py`, docstring) : *"This module has no dependency, so that decorators and models can be imported outside of the framework (e.g. by the pyscript client)."* Un commentaire identique existe dans `api/src/main/python/ycappuccino/api/http.py`.

### Méthode

Sur l'interpréteur CPython 3.14 de ce bac à sable (qui **n'a pas** `pelix`/`iPOPO` installé — vérifié : `import pelix` lève `ModuleNotFoundError`), avec seulement `api/src/main/python` et `core/src/main/python` ajoutés à `sys.path` (aucune installation `pip`/`uv`), tentative d'import module par module.

### Résultats (faits, pas suppositions)

**Import-clean (aucun `import pelix`, ni direct ni transitif, aucun `import yaml`)** — testé et confirmé par exécution réelle :

| Module | Imports externes réels |
|---|---|
| `ycappuccino.api.core_base` | `abc`, `typing`, `logging` (stdlib seul) |
| `ycappuccino.api.decorators` | `typing`, `functools` (stdlib seul) |
| `ycappuccino.api.models` | `ycappuccino.api.decorators` uniquement |
| `ycappuccino.api.http` | `abc`, `dataclasses`, `ycappuccino.api.core_base` |
| `ycappuccino.api.proxy` | `types`, `json`, `pprint`, `ycappuccino.api.core_base` |
| `ycappuccino.api.storage` | `abc`, `typing`, `ycappuccino.api.core_base`, `ycappuccino.api.models`, `ycappuccino.api.proxy` |
| `ycappuccino.api.endpoints_storage` | `abc`, `typing`, `ycappuccino.api.core_base` |
| `ycappuccino.api.endpoints_service` | `abc`, `dataclasses`, `typing`, `ycappuccino.api.core_base` |
| `ycappuccino.api.http_server` | `abc`, `typing`, `ycappuccino.api.core_base` |
| `ycappuccino.core.utils` | aucun import (juste des dict/constantes module-level) |
| `ycappuccino.core.decorator_app` | `ycappuccino.core.utils` uniquement |

Commande exacte utilisée (reproductible) :

```bash
python3 -c "
import sys
sys.path.insert(0, '.../api/src/main/python')
sys.path.insert(0, '.../core/src/main/python')
import ycappuccino.api.decorators, ycappuccino.api.models, ycappuccino.api.core_base
import ycappuccino.api.http, ycappuccino.api.storage
import ycappuccino.api.endpoints_storage, ycappuccino.api.endpoints_service, ycappuccino.api.http_server
import ycappuccino.core.decorator_app, ycappuccino.core.utils
print('OK')
"
# -> OK, sans que 'pelix' apparaisse dans sys.modules
```

**Non import-clean (nécessitent réellement `pelix`)** — confirmé en observant l'échec réel (`ModuleNotFoundError: No module named 'pelix'`) :

| Module | Raison |
|---|---|
| `ycappuccino.api.component_creator` | `from pelix.ipopo.decorators import Property` en ligne 1 : import direct de pelix |
| `ycappuccino.core.framework` | importe iPOPO/Pelix pour démarrer le vrai framework OSGi |
| `ycappuccino.core.runner` | importe `core.framework` |
| (par transitivité, non testés un par un mais dépendant de `component_creator`/`framework`) : `ycappuccino.api.remote`, `ycappuccino.api.scheduler`, `ycappuccino.api.scripts`, `ycappuccino.api.permissions`, `ycappuccino.api.hosts` | importent `ycappuccino.api.proxy.YCappuccinoRemote` — **`proxy` lui-même est clean**, ces modules le sont donc probablement aussi ; non nécessaires au client, non vérifiés individuellement pour ne pas gonfler cette section |

### Correction par rapport à la formulation initiale de la tâche

La consigne envisageait que `api.storage` pourrait ne **pas** être clean ("not `api.storage`"). **Fait vérifié : c'est faux** — `api.storage` (le port `IManager`/`ITrigger`/`IFilter`, pas l'implémentation mémoire/Mongo qui vit dans le dépôt `storage`) importe seulement `core_base`, `models` et `proxy`, tous les trois clean. Le sous-ensemble réellement clean est donc plus large que supposé : la quasi-totalité d'`api` sauf `component_creator` (et les modules qui ne dépendent que de lui/`framework`, non utiles au client).

### Deuxième constat empirique, décisif pour l'emballage : la dépendance déclarée dans `pyproject.toml` n'est PAS le graphe d'import

`api/pyproject.toml` déclare `dependencies = ["iPOPO>=3.0"]` **sans condition ni extra**. Conséquence vérifiée : `uv add --editable ../api` dans un projet neuf installe bien iPOPO et sa dépendance `jsonrpclib-pelix`, même si aucun module réellement importé n'en a besoin :

```
$ uv add --editable /home/.../api
Resolved 4 packages ...
 + ipopo==3.2.2
 + jsonrpclib-pelix==1.1.0
 + ycappuccino-api==0.1.0 (from file:///.../api)
```

**Implication pour Pyodide** : `micropip.install()` résout par défaut les dépendances déclarées dans les métadonnées du wheel. Installer le wheel `ycappuccino-api` tel quel dans Pyodide déclencherait donc une tentative d'installation d'`iPOPO`/`jsonrpclib-pelix`, dont la compatibilité Pyodide est inconnue et non nécessaire ici. **Décision : le bootstrap navigateur doit appeler `micropip.install(url, deps=False)`** pour les wheels `ycappuccino-api`/`ycappuccino-core`, ce qui installe le code du module sans résoudre ses dépendances déclarées — sûr précisément parce que le constat ci-dessus prouve que les modules réellement importés par le client n'en ont pas besoin à l'exécution.

### Ce que cela valide

Le postulat central est confirmé : un module de modèles `@Item` écrit pour le serveur (ex. `library/books.py` du dépôt `storage`, ou son équivalent dans `client/example/`) — s'il n'importe que `ycappuccino.api.decorators` / `ycappuccino.api.models` (jamais `api.component_creator`, jamais `core.framework`/`core.runner`, jamais Pelix directement) — est importable et utilisable tel quel dans Pyodide, sans compilation ni adaptation, avec la même sémantique (`get_storage_model()`, setters `@Property`) qu'côté serveur.

### Ce qui reste non vérifié (hors de portée de ce bac à sable)

- Que Pyodide/Wasm exécute réellement ces modules sans surprise (pas d'API CPython C absente, pas de récursion `sys.path` différente). Le code de ces modules est du Python pur stdlib (`abc`, `typing`, `functools`, `dataclasses`) : risque jugé très faible, mais **non prouvé en conditions réelles Pyodide**.
- Que `micropip.install(url, deps=False)` se comporte comme documenté sur la version de Pyodide réellement utilisée.
- Que `pyodide.http.pyfetch` fonctionne comme utilisé dans `ycappuccino.client.http` (voir §3).

## 1. Domaine et périmètre

Le client est un **client HTTP pur** pour l'API exposée par `http_server` (voir `http_server/README.md`) : enveloppe `{"status", "meta", "data"}`, routes `/api/crud/<pluriel>`, `/api/drafts/...`, `/api/items/...`, `/api/services/<nom>`. Il ne réimplémente aucune logique métier : il sérialise des requêtes HTTP et désérialise l'enveloppe JSON.

Il n'est **pas** un `YCappuccinoComponent` : pas de Pelix, pas de framework, pas de cycle de vie `start`/`stop` géré par un conteneur — un simple objet Python asynchrone instancié par le script de la page.

Hors périmètre (documenté, pas construit) :
- Installation réelle depuis PyPI : `ycappuccino-api`/`ycappuccino-core`/`ycappuccino-client` n'y sont pas publiés. En déploiement réel, les wheels sont construites (`uv build`) et servies par un `Host` (dépôt `hosts`) à une URL statique, puis installées par `micropip.install(url, deps=False)` (voir §0). CI/publication vers un vrai index : hors périmètre de ce sous-projet.
- Un vrai test en navigateur (Pyodide réel) : impossible dans ce bac à sable (pas de réseau pour charger le CDN). Tout ce qui touche `pyodide.http.pyfetch` et `static/index.html`/`static/main.py` est écrit avec soin mais **marqué vérification manuelle requise**.
- L'authentification (JWT) : le client accepte un jeton optionnel et l'envoie en `Authorization: Bearer <token>`, comme le lit `IAuthentication` côté serveur (voir `http_server/README.md`) ; aucune logique de rafraîchissement de jeton, de login, etc.

## 2. Le client HTTP (`ycappuccino.client.http`)

### Décision : refléter les signatures serveur, pas les réinventer

`endpoints_storage.ICrud` et `endpoints_service.IServiceEndpoint` (les deux ports que `http_server` adapte) donnent le vocabulaire : mêmes noms de méthode, même ordre de paramètres (moins `subject`, qui n'existe pas côté client — c'est le serveur qui le déduit des en-têtes HTTP), pour que le modèle mental d'un développeur habitué au serveur transfère directement.

| Méthode client (`ApiClient`) | Route HTTP | Équivalent serveur |
|---|---|---|
| `get_one(plural, id, params=None)` | `GET /api/crud/<plural>/<id>` | `ICrud.get_one` |
| `get_many(plural, params=None)` | `GET /api/crud/<plural>` | `ICrud.get_many` |
| `create(plural, fields)` | `POST /api/crud/<plural>` | `ICrud.create` |
| `update(plural, id, fields)` | `PUT /api/crud/<plural>/<id>` | `ICrud.update` |
| `delete(plural, id)` | `DELETE /api/crud/<plural>/<id>` | `ICrud.delete` |
| `delete_many(plural, filter)` | `DELETE /api/crud/<plural>?filter=...` | `ICrud.delete_many` |
| `call(name, method="POST", extra_path=None, params=None, body=None)` | `<method> /api/services/<name>[/<segment>...]` | `IServiceEndpoint.call` |

`get_many` retourne `{"items": [...], "total": <meta.size>}` (même forme que `ICrud.get_many`), reconstruit depuis l'enveloppe (`data` -> `items`, `meta.size` -> `total`). `delete_many` retourne l'entier supprimé (`data["deleted"]`), comme `ICrud.delete_many -> int`. `call` retourne directement `data` (le corps de `ServiceResult`).

### Encodage des paramètres

Une requête `GET`/`DELETE` transmet ses paramètres en query string ; `filter`/`sort` sont des dicts côté appelant Python mais du texte JSON côté HTTP (cf. `storage/README.md` : *"Les valeurs texte correspondent à ce qu'envoie un client HTTP"*). `ApiClient` sérialise donc en JSON toute valeur `dict`/`list` d'un paramètre, laisse les scalaires tels quels.

### Erreurs : réutilisation directe d'`api.endpoints_storage`

Puisque `ycappuccino.api.endpoints_storage` est import-clean (§0) et déjà une dépendance du paquet `ycappuccino-client` (voir §4), `ApiClient` mappe les codes HTTP de retour vers **les mêmes classes d'exception** que celles que `http_server` traduit depuis `endpoints_storage` : 401 -> `NotAuthenticated`, 403 -> `Forbidden`, 404 -> `NotFound`, 400 -> `InvalidRequest`, autre code d'erreur -> `CrudError` générique. Un code applicatif qui attrape `NotFound` côté serveur (dans un test, ou dans une future Single Page App isomorphe) attrape la même classe côté client.

### Transport : `pyodide.http.pyfetch` avec repli explicite

`ApiClient` ne dépend jamais de `pyodide` au moment de l'import (sinon le paquet ne serait pas testable en CPython nu). Le transport est une fonction injectable :

```python
async def transport(method: str, url: str, headers: dict, body: bytes | None) -> RawResponse:
    ...  # -> RawResponse(status: int, headers: dict, body: bytes)
```

- Sans transport explicite, `ApiClient` tente `ycappuccino.client.pyodide_transport.pyodide_transport`, qui importe `pyodide.http` **à l'intérieur de la fonction** (pas au niveau module) : si `pyodide` n'est pas disponible (donc pas dans un navigateur), l'appel lève un `RuntimeError` explicite ("no transport available: not running under Pyodide; inject a Transport for testing") **au moment de l'appel**, jamais un `ImportError` silencieux ni un plantage à l'import du paquet.
- Pour les tests CPython, on injecte un `FakeTransport` (dict d'URL -> réponse, ou callable) : c'est ce que valide `test_http.py`.
- **Non vérifié ici** (pas de Pyodide réel dans ce bac à sable) : le comportement réel de `pyodide.http.pyfetch` (signature exacte des kwargs, forme de `FetchResponse`, gestion des credentials/cookies, CORS). Le code de `pyodide_transport.py` est écrit du mieux possible par lecture de la documentation Pyodide connue, mais **marqué vérification manuelle requise en navigateur**.

## 3. Modèles partagés : la preuve par le round-trip CPython

`client/example/library/books.py` définit un `Book(Model)` minimal, décoré `@Item`/`@Property`, qui n'importe que `ycappuccino.api.decorators` et `ycappuccino.api.models` (le sous-ensemble clean identifié en §0) — **aucune dépendance à `storage`, `core`, ni au reste d'`api`**. C'est délibérément un fichier auteur d'application, pas un fichier framework : c'est exactement la classe qu'un développeur écrirait pour son serveur `ycappuccino-storage` (voir `storage/example/library/books.py`, structurellement identique) et qui doit rester utilisable telle quelle côté navigateur.

Le test `test_models.py` prouve, en CPython pur (donc sans lien avec un vrai Pyodide, mais valide puisque le module ne contient aucun code spécifique à Pyodide) :
1. Un document JSON tel qu'il sortirait de `ApiClient.get_one("books", "dune")` (donc de l'enveloppe HTTP, donc un `dict` pur) peut construire un `Book` : `Book(document)` puis `book.on_read(False)` (même séquence que `ycappuccino.storage.manager.Manager.get_one`, cf. `storage/src/main/python/ycappuccino/storage/manager.py`).
2. `book.get_storage_model()` redonne le document d'origine (round-trip).
3. Le test enchaîne réellement `ApiClient` (avec un `FakeTransport` renvoyant l'enveloppe JSON) -> `Book` -> `get_storage_model()`, pour prouver la chaîne complète "récupéré par HTTP -> modèle partagé" sans jamais avoir besoin d'un vrai serveur ni d'un vrai navigateur.

## 4. Emballage : deux paquets, une seule intention

| Partie | Nature | Où |
|---|---|---|
| `ycappuccino.client.http` (+ `pyodide_transport`) | paquet Python pur, `uv_build`, testable en CPython | `client/src/main/python/ycappuccino/client/` |
| `client/example/library/books.py` | modèle `@Item` d'exemple, pas empaqueté dans le wheel (dossier `example/`, comme les autres dépôts) | `client/example/` |
| `client/static/index.html`, `client/static/main.py` | assets statiques servis par un `Host` (dépôt `hosts`), jamais exécutés ni testés en CPython | `client/static/` |

Ce n'est **pas** un wheel `uv_build` unique contenant les assets navigateur : `hosts.Host.directory` pointe vers un répertoire de fichiers statiques (HTML/JS/py bruts), pas vers un paquet Python installé. `ycappuccino-client` (le wheel) et `client/static/` (les assets) ont des cycles de vie et des consommateurs différents : le premier est `pip`/`uv`-installable et testé par `unittest` ; le second est copié/servi tel quel par un `Host`.

`pyproject.toml` déclare `ycappuccino-api`/`ycappuccino-core` comme sources locales éditables, **exactement comme les dépôts voisins** (`storage`, `http_server`, `swagger`...). Ce choix pull `iPOPO`/`jsonrpclib-pelix`/`PyYAML` dans le `.venv` de développement du client (§0, deuxième constat) — **sans conséquence** puisque ce `.venv` ne sert qu'à exécuter `unittest` en CPython sur la machine du développeur, jamais à produire ce qui tourne dans le navigateur. Le bootstrap navigateur (§5) est un chemin d'installation entièrement différent (`micropip.install(url, deps=False)`), qui n'installe explicitement que le code, pas les dépendances déclarées.

## 5. `static/index.html` + `static/main.py` : ce qu'ils font, ce qui n'est pas vérifié

Objectif : la démo la plus petite et la plus évidemment correcte par lecture, pas un exemple riche.

- `index.html` charge pyscript depuis un CDN, épinglé explicitement : `https://pyscript.net/releases/2024.11.1/core.js` (+ `core.css`). Convention alignée sur celle déjà présente dans le dépôt `swagger` (`ui.py`), qui épingle aussi une version exacte sur un CDN (`unpkg.com/swagger-ui-dist@4.5.0`) plutôt qu'un `@latest`.
- `main.py` (chargé en `<script type="py" src="./main.py">`) : appelle `pyodide.http.pyfetch("/api/items")`, parse l'enveloppe JSON, écrit la liste des items (`id`/`plural`) dans un `<ul id="items">` du DOM via `pyscript.document`/`js.document`. Ne dépend pas du paquet `ycappuccino-client` (pour rester lisible et autonome) ; un commentaire du fichier explique comment le brancher sur `ApiClient` une fois les wheels installées via `micropip.install(..., deps=False)`.
- **Non vérifiable ici** (pas de réseau, pas de navigateur réel) : que le CDN répond, que la version épinglée existe encore, que `pyscript.document`/`js` exposent l'API attendue dans cette release, que le fetch same-origin/`CORS` fonctionne face à un vrai `http_server`. **Vérification manuelle en navigateur requise avant toute mise en production.**

## 6. Fichiers

```
client/
  pyproject.toml
  README.md
  .gitignore
  docs/superpowers/specs/2026-09-15-client-design.md
  docs/superpowers/plans/2026-09-15-client.md
  src/main/python/ycappuccino/client/__init__.py
  src/main/python/ycappuccino/client/http.py
  src/main/python/ycappuccino/client/pyodide_transport.py
  src/unittest/python/fake_transport.py
  src/unittest/python/test_http.py
  src/unittest/python/test_models.py
  src/unittest/python/test_readme.py
  example/library/__init__.py
  example/library/books.py
  static/index.html
  static/main.py
```

## 7. Développer

```bash
uv sync
uv run python -m unittest discover -s src/unittest/python
```

Rien dans `static/` n'est exécuté par cette commande : c'est attendu, ce sont des assets navigateur, pas du code Python testable ici.
