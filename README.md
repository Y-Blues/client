# ycappuccino-client

Client navigateur pour un serveur `ycappuccino` exposé par `ycappuccino-http-server` — pas un client HTTP bespoke, mais le vrai `ycappuccino.core.framework.Framework` (vrai Pelix/iPOPO), chargé dans le navigateur via Pyodide. Le code applicatif dépend des vraies interfaces `ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint` (`ycappuccino.api.endpoints_storage`/`endpoints_service`), exactement comme du code serveur — ce dépôt fournit une implémentation « remote » de chacune (HTTP/`fetch`), auto-découverte par le scan `bundle_prefix` dès que `ycappuccino.client` y figure, sans qu'aucun code applicatif ne les nomme ni ne les construise à la main.

Conception : [docs/superpowers/specs/2026-09-15-client-design.md](docs/superpowers/specs/2026-09-15-client-design.md).

Prérequis : lire les README de [core](../core/README.md) (« Écrire un composant », « Installer un composant à l'exécution », « Tester ses composants »), d'[endpoints_storage](../endpoints_storage/README.md), d'[endpoints_service](../endpoints_service/README.md), d'[http_server](../http_server/README.md) (le protocole HTTP exact que ce dépôt traduit) et de [remote](../remote/README.md) (le précédent : un « client de service distant » côté serveur, dont ce dépôt reprend la logique de traduction d'erreurs, en l'adaptant pour le navigateur et en l'étendant au CRUD).

**Risque assumé et accepté explicitement par l'utilisateur, à lire avant tout le reste : voir « §0 Risques d'exécution navigateur » de la spec.** `core.async_runner.AsyncRunner` démarre un vrai thread OS pour ponter les méthodes async des composants vers les callbacks synchrones de Pelix ; un build Pyodide standard mono-thread ne peut pas démarrer de vrai thread OS. Rien de ce qui touche un navigateur réel n'a pu être vérifié dans le bac à sable qui a produit ce dépôt.

## Ce que le code applicatif écrit (jamais `ycappuccino.client` directement)

Exactement comme sur un vrai backend : un composant natif déclare une dépendance sur l'interface, jamais sur une implémentation.

```python
from ycappuccino.api.core_base import YCappuccinoComponent
from ycappuccino.api.endpoints_storage import ICrud, IItemCatalog


class Catalog(YCappuccinoComponent):
    def __init__(self, crud: ICrud, catalog: IItemCatalog):
        self._crud = crud
        self._catalog = catalog

    async def start(self):
        self.items = await self._catalog.get_items()

    async def stop(self):
        pass
```

`conf/application.yml` :

```yaml
name: myapp
bundle_prefix:
  - ycappuccino.client   # fournit ICrud/IDrafts/IItemCatalog/IServiceEndpoint "remote"
  - myapp
```

Lister `ycappuccino.client` dans `bundle_prefix` suffit à faire résoudre `ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint` vers `RemoteCrud`/`RemoteDrafts`/`RemoteItemCatalog`/`RemoteServiceEndpoint` — exactement la même ergonomie que `ycappuccino.storage` donnant un `IManager` fonctionnel, ou `ycappuccino.endpoints_service` un `IServiceEndpoint`. Dans le navigateur, il n'existe aucune autre implémentation de ces interfaces (pas de vraie logique métier locale) : la résolution Pelix/iPOPO — un mécanisme de DI générique, pas un mécanisme spécial pour ce dépôt — ne trouve que celle-ci. `RemoteCrud`, `RemoteDrafts`, `RemoteItemCatalog`, `RemoteServiceEndpoint` et `HttpTransport` (`ycappuccino.client.components`/`transport`) restent des détails d'implémentation internes : importables pour les tests, jamais nommés par du code applicatif.

### Comment les quatre `Remote*` existent, sans être écrits à la main

`ycappuccino/client/components.py` contient exactement ceci :

```python
RemoteCrud = make_remote(ICrud, "crud", catalog=IItemCatalog)
RemoteDrafts = make_remote(IDrafts, "drafts", catalog=IItemCatalog)
RemoteItemCatalog = make_remote(IItemCatalog, "items")
RemoteServiceEndpoint = make_remote(IServiceEndpoint, "services")
```

`make_remote` (`ycappuccino.client.remote_proxy`) synthétise chaque classe **par réflexion** sur l'interface `api` — aucune méthode écrite à la main, aucune table `{méthode → route}` : le verbe HTTP, le chemin et la forme du résultat sont dérivés du **nom** de chaque méthode et des **noms** de ses paramètres, selon cinq conventions précises documentées dans la spec, [§9](docs/superpowers/specs/2026-09-15-client-design.md#9-v3--make_remote-fabrique-générique-par-réflexion) — y compris leurs limites honnêtes (un nom de méthode mal choisi sur une future interface pourrait être mal routé sans qu'aucun test ne puisse le prédire à l'avance). Demandé et choisi explicitement par l'utilisateur (réflexion pure plutôt qu'une table déclarative), avec la fragilité assumée en connaissance de cause.

## Mise en place

Ce dépôt n'est **pas** un `Host` en lui-même : ses assets navigateur (`static/`) sont destinés à être servis par un `Host` du dépôt [hosts](../hosts/README.md) (`Host.directory` pointant vers une copie de `client/static`, éventuellement avec `cross_origin_isolated: true` — voir « Risques d'exécution navigateur » plus bas). La partie testable en CPython s'installe comme les autres dépôts :

```bash
uv add --editable ../client
```

## Session / authentification : `HttpTransport`

`HttpTransport` (`ycappuccino.client.transport`) est le composant natif unique dont dépendent les quatre `Remote*` — un vrai singleton Pelix, injecté par le conteneur, pas une variable globale. Il porte :

- l'URL de base des requêtes (`/api` par défaut — chemin relatif, même origine que la page, puisque le client est servi par le même backend qu'il appelle via un `Host`), surchargeable par `IConfiguration` sous la clé `client.base_url` de `conf/config.properties`, lue une fois au `start()` (pas de rechargement à chaud, même convention que `scheduler`/`hosts`) ;
- le jeton porteur courant, en mémoire : `set_token(token)` / `get_token()` / `clear_token()`.

**Décision de conception (spec A.2)** : pas de composant `BrowserSession` séparé. Il n'existe qu'un seul transport ; scinder le jeton dans un second composant n'ajouterait qu'un saut de câblage supplémentaire, sans bénéfice comportemental. Un flux de connexion (mirroring `permissions_app`'s `LoginService`) ressemble à :

```python
from ycappuccino.api.core_base import YCappuccinoComponent
from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.client.transport import HttpTransport


class Login(YCappuccinoComponent):
    def __init__(self, services: IServiceEndpoint, transport: HttpTransport):
        self._services = services
        self._transport = transport

    async def stop(self):
        pass

    async def start(self):
        pass

    async def log_in(self, login: str, password: str) -> None:
        result = await self._services.call("login", "POST", [], {}, {"login": login, "password": password}, None)
        self._transport.set_token(result.body["token"])
```

`transport: HttpTransport` est ici une dépendance sur une **classe concrète**, pas une interface : `describe_component` (`ycappuccino.core.component_factory`) traite tout sous-type de `YCappuccinoComponent` comme un type injectable, interface ou non — `HttpTransport` est publié sous son propre nom de classe, comme n'importe quel composant natif (`core/README.md` : « Services publiés »).

### Le paramètre `subject` : conservé, mais ignoré (décision A.1)

`ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint` prennent tous un `subject` (côté serveur : le dict décodé du JWT, `{"sub", "tid"}`). Les `Remote*` de ce dépôt **conservent ce paramètre dans leur signature, mais ignorent silencieusement sa valeur** : le navigateur ne décode jamais de JWT, et lever une erreur quand `subject is not None` casserait précisément le genre de code applicatif partagé (une fonction qui prend un `ICrud` et l'appelle pareil des deux côtés) que cette refonte cherche à permettre — un appelant qui passe un `subject` par habitude serveur ne doit pas voir son code casser spécifiquement au déploiement navigateur. C'est un compromis assumé (un `subject` passé par erreur est silencieusement sans effet, jamais signalé) plutôt que l'alternative plus stricte (`subject` doit être `None`, sinon erreur) : voir la spec §A.1 pour la discussion complète. L'authentification réelle est portée par `HttpTransport` (en-tête `Authorization: Bearer <jeton>`) ; c'est le serveur qui calcule son propre sujet à partir de ce jeton et décide de l'autorisation, exactement comme pour tout autre appelant HTTP.

## `item_id` → pluriel : résolution par `IItemCatalog`

`ICrud`/`IDrafts` prennent un `item_id` (ex. `"book"`), mais les routes `http_server` sont en pluriel (`/api/crud/books`, voir `ApiServlet._route_crud`, qui fait la résolution inverse via `catalog.get_item_by_plural(plural)["id"]`). `RemoteCrud`/`RemoteDrafts` prennent `IItemCatalog` en dépendance constructeur (dans les faits, l'aussi auto-découvert `RemoteItemCatalog`) et résolvent `item_id → plural` via `catalog.get_item(item_id)["plural"]`, plutôt que de supposer une convention de nommage (`item_id + "s"`) qui ne serait pas toujours correcte. C'est exactement le genre de câblage transversal entre composants pour lequel le vrai conteneur de DI existe.

`RemoteItemCatalog` récupère la liste des items **une seule fois, à `start()`** (`GET /api/items`), et la met en cache : `get_items()`/`get_item()`/`get_item_by_plural()` ne refont jamais de requête réseau — simplification délibérée, sans rechargement à chaud, même convention que `scheduler`/`hosts`. `get_schema()`/`get_empty()` ne font pas partie de cette liste et interrogent le réseau à chaque appel.

## Traduction des erreurs

`ycappuccino.client.transport.decode_envelope()` décode l'enveloppe `{"status", "meta", "data"}` (`http_server/README.md`) et lève la même famille d'erreurs que le serveur : `NotAuthenticated` (401), `Forbidden` (403), `NotFound` (404), `InvalidRequest` (400), `CrudError` générique sinon — logique adaptée de `remote/call.py`'s `_translate()` (pas importée : `client` ne dépend pas de `remote`, dont le modèle d'adressage — un registre de pairs nommés — ne s'applique pas ici : un seul backend fixe, même origine).

## Transport bas niveau : `pyodide.http.pyfetch`, avec repli explicite

`HttpTransport` n'importe jamais `pyodide` au niveau module. Sans `IHttpFetcher` publié, il utilise `ycappuccino.client.pyodide_transport.pyodide_transport`, qui importe `pyodide.http` **à l'intérieur de la fonction** : hors Pyodide, l'appel lève un `RuntimeError` explicite plutôt qu'un `ModuleNotFoundError` muet.

`IHttpFetcher` (`ycappuccino.client.transport`) est une interface de composant **définie dans ce dépôt**, pas dans `api` : `describe_component` accepte n'importe quel sous-type de `YCappuccinoComponent` comme dépendance injectable, ce n'est pas réservé aux interfaces déclarées dans `api`. En pratique, aucune implémentation n'est publiée en production (`HttpTransport` retombe alors sur `pyodide_transport`).

Pour les tests unitaires d'un seul composant (pas de framework du tout, voir `core/README.md` « Tester ses composants »), on construit directement `HttpTransport(fetcher=FakeFetcher(...))` — ceci **est** prouvé, exhaustivement, par `test_transport.py`/`test_remote_*.py`.

**Découverte réelle en écrivant le test d'intégration, pas une supposition** : publier un `IHttpFetcher` depuis un paquet applicatif (pour que le vrai framework le câble automatiquement dans `HttpTransport`) ne fonctionne **pas de façon fiable** dès que `HttpTransport` vit dans l'espace de noms `ycappuccino.*` et le fournisseur ailleurs — le même défaut que `hosts/servlet.py` documente déjà pour ses propres dépendances optionnelles. Voir spec §9.2 pour le diagnostic complet. `test_client_framework.py` contourne donc le problème autrement : il remplace directement `ycappuccino.client.pyodide_transport.pyodide_transport` (une simple affectation de fonction Python, aucun passage par la résolution de services Pelix) plutôt que de publier un `IHttpFetcher`.

## Modèle partagé, round-trip complet

`example/library/books.py` est un modèle `@Item` ordinaire, structurellement identique à celui qu'on écrirait pour un serveur `ycappuccino-storage` : il n'importe que `ycappuccino.api.decorators`/`ycappuccino.api.models` (le sous-ensemble import-clean identifié au §0 de la spec, toujours valide).

```python
from library.books import Book   # example/library/books.py

document = await crud.get_one("book", "dune")   # dict brut renvoyé par le serveur
book = Book(document)
book.on_read(False)                              # même séquence que ycappuccino.storage.manager.Manager.get_one
book.get_storage_model()                         # {"_id": "dune", "title": "Dune", "pages": 412}
```

`example/library/catalog.py` fournit `Catalog`, le composant de démo qui prouve le câblage bout en bout (voir sa docstring) : il dépend de `ICrud`/`IItemCatalog`, jamais de `ycappuccino.client`.

## Bootstrap navigateur : `static/index.html` + `static/main.py`

**Rien de cette séquence n'a pu être exécuté dans le bac à sable qui a produit ce dépôt (pas de réseau pour charger Pyodide/pyscript). Vérification manuelle en navigateur requise avant toute mise en production — voir « Limites et vérifications manuelles requises » ci-dessous.**

Séquence, dans l'ordre (voir spec §0.b/§0.c pour la justification détaillée de chaque étape) :

1. Charger Pyodide (page servie avec `Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy: require-corp`, et un build Pyodide **pthread** — voir « Risques d'exécution navigateur »).
2. `await pyodide.loadPackage("pyyaml")` — le chargeur de paquets **curaté** de Pyodide, choisi explicitement plutôt que de laisser `micropip` résoudre PyYAML lui-même (PyYAML a une extension C optionnelle ; le paquet curaté de Pyodide en fournit une version connue-compatible Wasm). **Non vérifié ici** : que `pyyaml` figure bien dans la liste curatée de la version de Pyodide réellement chargée — à vérifier contre la documentation Pyodide réelle avant mise en production.
3. `await micropip.install(url, deps=False)` pour `iPOPO`, `ycappuccino-api`, `ycappuccino-core`, `ycappuccino-client`, dans cet ordre — `deps=False` pour ne jamais laisser `micropip` tenter de résoudre les dépendances déclarées de ces wheels (voir §0, deuxième constat empirique, toujours valide : `api` déclare `iPOPO` sans condition, mais le sous-ensemble réellement importé par `client` n'en a pas besoin — sauf que `core.framework`, lui, a réellement besoin d'`iPOPO`/`pelix`, d'où son installation explicite ici, contrairement à l'ancienne conception qui ne chargeait jamais `core.framework` dans le navigateur).
4. Écrire `conf/application.yml` et le paquet de démo (`example/library/`) dans le système de fichiers virtuel de Pyodide, via de simples `open(path, "w")` Python — le FS de Pyodide le permet nativement, sans changer la signature de `Framework.init()` (qui exige un vrai chemin de fichier).
5. `Framework().init("conf/application.yml")` — démarre le vrai Pelix/iPOPO, scanne `bundle_prefix` (`ycappuccino.client`, `library`), démarre `HttpTransport`/`RemoteCrud`/`RemoteItemCatalog`/`RemoteServiceEndpoint`/`Catalog`.
6. Lire le service résolu par DI (`framework.context.get_service_reference("Catalog")` puis `get_service(...)`) et afficher `catalog.items` dans le DOM.

## Risques d'exécution navigateur (§0 de la spec — lire avant tout déploiement)

**(a) Threads réels — `AsyncRunner`.** `core.async_runner.AsyncRunner` fait tourner une boucle asyncio sur un **vrai thread OS** (`threading.Thread(target=loop.run_forever, daemon=True).start()`), démarré au premier appel, pour ponter les méthodes `async` des composants (`start`/`stop`/`handle`/...) vers les callbacks synchrones que Pelix attend. C'est le mécanisme qui fait tourner CHAQUE composant natif de ce framework, pas une fonctionnalité annexe : sans lui, aucun composant ne démarre. Un build Pyodide standard, mono-thread, ne peut **pas** démarrer de vrai thread OS. **Ce qu'on peut affirmer en lisant le code** : `threading.Thread(...).start()` est un appel bloquant qui délègue à `_thread.start_new_thread` (C) ; sous un CPython compilé sans support thread, cet appel lève une erreur à l'exécution (pas un plantage silencieux, pas un pur no-op), mais **la forme exacte de cette erreur sous Pyodide mono-thread (exception, message, ou tout autre comportement) n'a pas pu être vérifiée dans ce bac à sable** — aucun navigateur réel disponible, aucune installation Pyodide locale. **Prérequis pour que ça marche** : un build Pyodide **pthread** (compilé avec support des threads WebAssembly, via `SharedArrayBuffer`), servi par une page envoyant `Cross-Origin-Opener-Policy: same-origin` et `Cross-Origin-Embedder-Policy: require-corp` (`SharedArrayBuffer` est désactivé par les navigateurs modernes sans ces deux en-têtes). Voir Partie C ci-dessous (`hosts`) pour l'en-tête ajouté à cet effet. **Non vérifié ici, à vérifier en conditions réelles avant toute mise en production** : que la distribution standard `pyodide.js` d'un CDN sélectionne automatiquement (ou permette de sélectionner explicitement) un build pthread, et que ce build fonctionne réellement dans ce scénario une fois les en-têtes en place.

**(b) PyYAML dans le navigateur.** `Framework.init()` fait inconditionnellement `yaml.safe_load(open(yml_path))`. Décision : charger `pyyaml` via `pyodide.loadPackage("pyyaml")` (le chargeur curaté de Pyodide) **avant** les `micropip.install(..., deps=False)`, plutôt que de compter sur `micropip`/PyPI pour résoudre PyYAML (qui a une extension C optionnelle dont la compatibilité Wasm/PyPI n'est pas garantie par ce chemin). **Non vérifié ici** : que `pyyaml` figure réellement dans la liste de paquets curatés de la version de Pyodide chargée — à vérifier contre la documentation Pyodide réelle avant de s'appuyer dessus.

**(c) `Framework.init(yml_path)` veut un vrai chemin de fichier.** Résolu entièrement côté bootstrap (`static/main.py`), sans toucher `core` : `conf/application.yml` et les fichiers du paquet de démo sont écrits dans le système de fichiers virtuel de Pyodide avec de simples `open(path, "w")` Python avant l'appel à `init()` — le FS de Pyodide le permet nativement (mémoire, pas de disque réel).

**(d) `Set-Cookie` illisible en `fetch`.** Les navigateurs n'exposent jamais l'en-tête `Set-Cookie` d'une réponse à JavaScript/Pyodide (`fetch()`), par spécification. `RemoteServiceEndpoint`/`ServiceResult.headers` ne peuvent donc pas relayer un `Set-Cookie` de connexion (contrairement à `remote/call.py`, qui relaie des en-têtes serveur-à-serveur sans cette contrainte navigateur). D'où le choix de `permissions_app`'s `login` (pas `login_cookie`) comme mécanisme de connexion pour ce client : le jeton voyage dans le **corps** JSON de la réponse (`{"token": ...}`), lu explicitement par le code applicatif puis posé sur `HttpTransport.set_token()` — voir « Session / authentification » ci-dessus.

**(e) COOP/COEP contre les CDN tiers** — voir Partie C (`hosts`) : activer `cross_origin_isolated` sur le `Host` qui sert `client/static/` peut casser le chargement de Pyodide/pyscript depuis un CDN public si ce CDN n'envoie pas les en-têtes `Cross-Origin-Resource-Policy`/CORS compatibles — hors du contrôle de ce dépôt, non vérifiable ici.

## Limites et vérifications manuelles requises

Rien de ce qui touche un navigateur réel n'a pu être exécuté dans l'environnement qui a produit ce dépôt (pas de réseau pour charger Pyodide/pyscript depuis un CDN, pas de navigateur). Précisément, **ne sont pas prouvés ici, et nécessitent une vérification manuelle en navigateur avant mise en production** :

- **Threads réels sous Pyodide** (risque (a) ci-dessus) : qu'un build Pyodide pthread démarre effectivement `AsyncRunner` correctement une fois COOP/COEP en place ; la forme exacte de l'échec si ce n'est pas le cas.
- **`pyyaml` dans la liste curatée de Pyodide** (risque (b)) : à vérifier contre la documentation Pyodide de la version réellement chargée.
- **`micropip.install(url, deps=False)` pour `iPOPO`** : qu'iPOPO (une dépendance C-free en théorie, mais jamais testée sous Wasm dans ce bac à sable) s'installe et fonctionne réellement sous Pyodide — c'est la brique la plus risquée de toute la chaîne, puisque tout le reste (framework, DI, async_runner) en dépend directement.
- **Le comportement réel de `pyodide.http.pyfetch`** (`pyodide_transport.py`) : noms exacts des options, forme de `FetchResponse`, gestion CORS/`credentials`.
- **`static/index.html`/`static/main.py`** : que le CDN pyscript/Pyodide pinné existe encore et réponde, que l'API utilisée est bien celle de la version chargée, que le `fetch` de `/api/...` aboutisse face à un vrai `http_server` (same-origin).
- **COOP/COEP + CDN tiers** (risque (e)) : qu'un CDN public pyscript/Pyodide envoie des en-têtes compatibles avec `Cross-Origin-Embedder-Policy: require-corp` une fois ce mode activé sur le `Host`.
- **La construction réelle des wheels** `ycappuccino-api`/`ycappuccino-core`/`ycappuccino-client` et leur mise à disposition par un `Host` : non faite ici (hors réseau/index de paquets réel).

Ce qui **est** prouvé, par exécution réelle dans ce bac à sable : le câblage DI complet en CPython pur (`test_client_framework.py` — un vrai `Framework()`, un vrai scan `bundle_prefix` incluant `ycappuccino.client`, une vraie résolution `ICrud`/`IItemCatalog`/`IServiceEndpoint` → `RemoteCrud`/`RemoteItemCatalog`/`RemoteServiceEndpoint` avec leur vrai `__init__` forgé par `exec` — seul le dernier maillon, l'appel HTTP bas niveau, étant remplacé par une fonction falsifiée, voir « Transport bas niveau » ci-dessus pour pourquoi ce n'est pas un `IHttpFetcher` publié), le comportement unitaire exhaustif (un test par méthode, verbe/chemin/corps/query exacts) de chaque `Remote*`/`HttpTransport`/`decode_envelope` avec un transport falsifié, et le round-trip `document -> Book -> get_storage_model()`.

## Développer client

```bash
uv sync
uv run python -m unittest discover -s src/unittest/python
```

`static/` n'est pas exécuté par cette commande : ce sont des assets navigateur, pas du code Python testable en CPython.
