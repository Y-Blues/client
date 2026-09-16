# client navigateur : design (v3 — RemoteCrud/RemoteDrafts/RemoteItemCatalog/RemoteServiceEndpoint synthétisés par réflexion)

Date de la conception initiale : 2026-09-15. **Révision du 2026-09-16 (v2)** : refonte complète, demandée explicitement par l'utilisateur après rejet de la première approche (un `ApiClient` HTTP bespoke). Nouvelle ambition, assumée avec ses risques : **le navigateur charge le vrai `ycappuccino.core.framework.Framework`** (vrai Pelix/iPOPO), et le code applicatif dépend des vraies interfaces `ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint` (`ycappuccino.api.endpoints_storage`/`endpoints_service`), avec une implémentation « remote » de chacune (HTTP/`fetch`) injectée dessous par le même conteneur de DI que côté serveur — le code applicatif ne sait jamais qu'un appel traverse une frontière HTTP. C'est ce que le dépôt `remote` fait déjà pour les appels serveur-à-serveur (`RemoteCall implements IExposedService`), étendu au navigateur et au CRUD.

**Révision du même jour (v3)**, demandée explicitement par l'utilisateur juste après la v2 : « je veux avoir le code client comme le code backend, sans différence, juste un outil générique dans client qui crée le lien pour appeler le distant, comme dans le dépôt `remote` ». Clarifié avec l'utilisateur (deux options présentées, avec extraits de code) : il choisit explicitement la **réflexion pure, zéro donnée de route déclarative par interface** — pas de table de routes, pas de corps de méthode écrit à la main par interface. Les quatre classes `Remote*` de la v2 (`remote_crud.py`, `remote_drafts.py`, `remote_item_catalog.py`, `remote_service_endpoint.py`, un fichier par interface, chacun avec un corps de méthode écrit à la main par méthode) sont **remplacées par une seule fabrique générique**, `ycappuccino.client.remote_proxy.make_remote(interface, resource, **extra_deps)`, plus quatre affectations d'une ligne au niveau module (`ycappuccino/client/components.py`) — voir §9 pour la conception complète, les cinq conventions exactes qui rendent cette réflexion possible, et les limites honnêtes de l'approche (l'utilisateur a été prévenu de sa fragilité et l'a choisie en connaissance de cause). Tout le reste de la v2 (§0 à §8) reste valide tel quel : `HttpTransport`/`IHttpFetcher`/`decode_envelope`, la décision `subject` ignoré (A.1), l'URL de base via `IConfiguration` (A.3), et surtout l'ergonomie côté application (`bundle_prefix: ycappuccino.client` suffit, le code applicatif ne dépend que des interfaces `api`) ne changent pas — seule l'implémentation interne des quatre `Remote*` change.

**Ce risque a été explicitement signalé à l'utilisateur, et explicitement accepté par lui** : `core.async_runner.AsyncRunner` démarre un vrai thread OS pour ponter les méthodes async des composants vers les callbacks synchrones de Pelix ; un build Pyodide standard mono-thread ne peut pas démarrer de vrai thread OS. Ce document ne dilue pas ce risque pour l'éviter — voir §0bis, qui le documente précisément, avec ce qui est vérifiable par lecture du code et ce qui ne l'est pas sans navigateur réel.

## 0. Validation empirique du sous-ensemble import-clean (inchangé, toujours valide)

Cette section date de la première conception et reste valide telle quelle : rien dans la refonte ne change le graphe d'import d'`api`. Elle gate toujours la faisabilité du chargement de modèles/interfaces `api` sous Pyodide.

### Méthode et résultat

Sur l'interpréteur CPython de ce bac à sable (sans `pelix`/`iPOPO` installés), avec seulement `api/src/main/python` et `core/src/main/python` ajoutés à `sys.path` :

**Import-clean (aucun `import pelix`, ni direct ni transitif)** :

| Module | Imports externes réels |
|---|---|
| `ycappuccino.api.core_base` | stdlib seul |
| `ycappuccino.api.decorators` | stdlib seul |
| `ycappuccino.api.models` | `ycappuccino.api.decorators` |
| `ycappuccino.api.http` | `ycappuccino.api.core_base` |
| `ycappuccino.api.proxy` | `ycappuccino.api.core_base` |
| `ycappuccino.api.storage` | `core_base`, `models`, `proxy` |
| `ycappuccino.api.endpoints_storage` | `ycappuccino.api.core_base` |
| `ycappuccino.api.endpoints_service` | `ycappuccino.api.core_base` |
| `ycappuccino.api.http_server` | `ycappuccino.api.core_base` |
| `ycappuccino.core.utils` | aucun |
| `ycappuccino.core.decorator_app` | `ycappuccino.core.utils` |

**Non import-clean (nécessitent réellement `pelix`)** : `ycappuccino.api.component_creator` (import direct), `ycappuccino.core.framework`, `ycappuccino.core.runner`, `ycappuccino.core.component_factory`, `ycappuccino.core.async_runner` (indirectement, via `framework`).

**Différence décisive avec la v1** : la v1 concluait que le client ne devait **jamais** charger `core.framework` (non clean, jugé hors de portée). La v2 le charge **délibérément** : c'est tout l'objet de la refonte. `iPOPO`/`pelix` deviennent donc de vraies dépendances d'exécution du bundle navigateur, pas seulement une dépendance déclarée-mais-inutilisée comme en v1 — voir §0bis(c) pour ce que cela implique côté empaquetage.

### Deuxième constat empirique (inchangé) : la dépendance déclarée n'est pas le graphe d'import réel

`api/pyproject.toml` déclare `iPOPO>=3.0` sans condition ; `uv add --editable ../api` l'installe réellement. Ce constat justifiait `micropip.install(url, deps=False)` en v1 pour ne *jamais* installer iPOPO. En v2, iPOPO doit être installé — mais toujours explicitement, en tant que wheel nommé, jamais via la résolution automatique de dépendances de `micropip` (dont la compatibilité Pyodide de la résolution elle-même n'est de toute façon pas vérifiée ici) : voir §0bis(b)/(c).

## 0bis. Risques d'exécution navigateur

Section requise explicitement par l'utilisateur, à lire avant tout le reste. Rien ici n'a pu être vérifié dans ce bac à sable (aucun accès réseau pour charger Pyodide/pyscript, aucun navigateur disponible).

### (a) `AsyncRunner` a besoin d'un vrai thread OS

`core/src/main/python/ycappuccino/core/async_runner.py` (lu intégralement) :

```python
class AsyncRunner(object):
    def _get_loop(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop.run_forever, name=self._name, daemon=True
                )
                self._thread.start()
            return self._loop
```

`run()` route soit vers `asyncio.run_coroutine_threadsafe(..., self._get_loop())` (cas normal : un appelant hors du thread du runner), soit vers un `ThreadPoolExecutor` d'appoint (cas de ré-entrance : un appel imbriqué depuis une coroutine qui tourne déjà sur la boucle). Dans les deux cas, **au moins un vrai thread OS est démarré au premier appel**, et c'est `Framework._install_component`/`create_factory_module` (`core/component_factory.py`) qui appelle `runner.run(self._obj.start())` pour **chaque composant natif** au moment de sa validation Pelix — donc ce mécanisme n'est pas une fonctionnalité annexe : c'est ce qui fait démarrer chaque composant du framework, `HttpTransport`/`RemoteCrud`/... compris.

**Ce qu'on peut affirmer avec certitude, par lecture du code CPython/stdlib** : `threading.Thread(...).start()` délègue in fine à `_thread.start_new_thread` (module C). Sous un interpréteur compilé sans support des threads réels, cet appel **lève une exception à l'exécution** (ce n'est ni un plantage silencieux à l'import, ni un no-op qui laisserait le programme continuer comme si de rien n'était) — c'est le comportement CPython documenté de longue date pour `_thread` sur une build sans threads.

**Ce qui n'est PAS vérifiable ici** : la forme exacte de cette erreur sous un build **Pyodide** mono-thread précisément (le message, la classe d'exception, si Pyodide simule un `_thread` factice qui échoue différemment de CPython nu) — aucune installation Pyodide, aucun navigateur, aucun réseau disponibles dans ce bac à sable pour le constater. Ce document ne prétend donc PAS savoir si le framework « plante proprement avec un message clair » ou « plante de façon confuse » sous un Pyodide non threadé : les deux sont plausibles, seul un test en navigateur réel tranchera.

**Prérequis pour que ça marche du tout** : un build Pyodide **pthread** (compilé avec le support des threads WebAssembly, qui repose sur `SharedArrayBuffer`), servi par une page envoyant `Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy: require-corp` (ces deux en-têtes sont la condition posée par les navigateurs modernes pour autoriser `SharedArrayBuffer`, suite aux mitigations Spectre). Voir Partie C (`hosts`, `Host.cross_origin_isolated`) pour l'ajout correspondant. **Non vérifié ici** : que la distribution standard `pyodide.js` d'un CDN (celle référencée par `static/index.html`) sélectionne automatiquement, ou permette de sélectionner explicitement, un build pthread ; ni que ce build fonctionne réellement une fois les en-têtes en place. À vérifier contre la documentation Pyodide réelle avant toute mise en production.

### (b) PyYAML dans le navigateur

`Framework.init(yml_path)` (`core/framework.py`, ligne ~222) fait inconditionnellement :

```python
with open(yml_path, "r") as file:
    self.application_yaml = yaml.safe_load(file) or {}
```

`PyYAML` a une extension C optionnelle (`LibYAML`/`CSafeLoader`) dont la compatibilité Wasm n'est pas garantie a priori. **Décision** : charger `pyyaml` via le chargeur de paquets **curaté** de Pyodide, `await pyodide.loadPackage("pyyaml")` — appelé côté Python via le pont `pyodide_js` (`import pyodide_js; await pyodide_js.loadPackage("pyyaml")`, voir `static/main.py`) — **avant** tout `micropip.install`, plutôt que de laisser `micropip`/PyPI résoudre PyYAML lui-même. **Non vérifié ici, à vérifier contre la documentation Pyodide réelle avant mise en production** : (1) que `pyyaml` figure bien dans la liste de paquets curatés de la version de Pyodide effectivement chargée par `static/index.html` ; (2) que `pyodide_js.loadPackage` est bien la façon documentée d'appeler `pyodide.loadPackage` depuis du code Python tournant dans Pyodide (écrit à partir de la connaissance de l'existence d'un module-pont `pyodide_js`, non confirmé contre la documentation Pyodide réelle dans ce bac à sable).

### (c) `Framework.init(yml_path)` veut un vrai chemin de fichier — résolu côté bootstrap, pas dans `core`

`init()` fait `open(yml_path, "r")` : un vrai chemin de fichier, pas une chaîne YAML en mémoire. **`core` n'est pas modifié** pour changer cette signature. Résolu entièrement dans `static/main.py` : `conf/application.yml` et les modules du paquet de démo (`bundle/library/...`) sont écrits dans le système de fichiers virtuel de Pyodide avec de simples `open(path, "w")` Python, **avant** l'appel à `Framework().init(...)` — le FS de Pyodide (mémoire, `MEMFS` par défaut) supporte cette écriture nativement, sans aucune API spéciale.

### (d) `Set-Cookie` illisible en `fetch` — conséquence sur le choix du service de connexion

Les navigateurs n'exposent jamais `Set-Cookie` à JavaScript/Pyodide via `fetch()`, par spécification (protection contre l'exfiltration de cookies). `permissions_app` expose deux services de connexion (`login` -> `{"token"}` dans le corps, `login_cookie` -> même chose + `Set-Cookie`, voir `permissions_app/README.md`). Le choix pour ce client est **`login`**, jamais `login_cookie` : le jeton voyage dans le corps JSON, lu explicitement par l'application, posé sur `HttpTransport.set_token()`. `RemoteServiceEndpoint`/`ServiceResult.headers` ne peuvent structurellement pas relayer un `Set-Cookie` utile ici, contrairement à `remote/call.py` qui relaie des en-têtes serveur-à-serveur sans cette contrainte.

### (e) COOP/COEP contre les CDN tiers — tension réelle, non résolue

Activer `Host.cross_origin_isolated` (voir Partie C) pour obtenir (a) peut **casser le chargement de Pyodide/pyscript depuis un CDN public** si ce CDN n'envoie pas lui-même des en-têtes `Cross-Origin-Resource-Policy`/CORS compatibles avec `Cross-Origin-Embedder-Policy: require-corp` (qui refuse de charger toute ressource cross-origin dépourvue de ces en-têtes). Ni `client` ni `hosts` ne contrôlent les en-têtes envoyés par un CDN tiers. **Non vérifiable dans ce bac à sable** (pas de réseau) : vérification manuelle en navigateur réel requise, propre à chaque CDN/déploiement.

## 1. Domaine et périmètre

Le client fournit quatre composants natifs — `RemoteCrud`, `RemoteDrafts`, `RemoteItemCatalog`, `RemoteServiceEndpoint` (`ycappuccino.client.remote_crud`/`remote_drafts`/`remote_item_catalog`/`remote_service_endpoint`) — qui **implémentent réellement** `ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint` (`ycappuccino.api.endpoints_storage`/`endpoints_service`), auto-découverts par `Framework.load_bundles()` dès que `bundle_prefix` contient `"ycappuccino.client"` — exactement l'ergonomie de `ycappuccino.storage` fournissant un `IManager`, ou d'`ycappuccino.endpoints_service` fournissant un `IServiceEndpoint`. Le code applicatif ne les nomme ni ne les construit jamais : il dépend des interfaces `api`, point.

Ce n'est **pas** un client HTTP autonome sans framework (c'était la v1) : c'est le vrai `Framework`, avec toute sa mécanique (DI par constructeur, cycle de vie `start`/`stop`, `AsyncRunner`, scan `bundle_prefix`), chargé sous Pyodide.

Hors périmètre (documenté, pas construit) : installation réelle depuis PyPI (les wheels `ycappuccino-api`/`-core`/`-client` n'y sont pas publiées — construites et servies par un `Host`, voir §6) ; un vrai test en navigateur (impossible dans ce bac à sable) ; la construction du build Pyodide pthread lui-même.

## 2. Décisions de conception (Partie A du mandat)

### A.1 — Le paramètre `subject` : conservé pour la signature, ignoré à l'exécution

`ICrud.get_one(self, item_id, id, params=None, subject=None)` (et les dix méthodes analogues d'`IDrafts`/`IItemCatalog`/`IServiceEndpoint.call`) prennent un `subject`. Côté serveur, c'est le dict JWT déjà décodé, utilisé par `IAuthorization.is_authorized`. Côté navigateur, il n'existe rien de tel : le navigateur ne décode jamais de JWT lui-même.

**Décision retenue : `subject` reste un paramètre de la signature (parité d'interface complète — le code type-check identiquement des deux côtés), mais sa valeur est silencieusement ignorée**, jamais inspectée, jamais transmise au serveur.

**Alternative rejetée, et pourquoi** : lever une erreur quand `subject is not None` (honnêteté stricte : « ce paramètre n'a pas de sens ici, ne prétends pas qu'il en a un »). Rejetée parce qu'elle romprait précisément la promesse centrale de cette refonte — qu'une fonction/​un composant écrit pour prendre un `ICrud` en dépendance et l'appeler avec un `subject` (un style de code tout à fait normal et attendu côté serveur, par ex. un middleware d'audit générique) **casserait spécifiquement au déploiement navigateur**, en réintroduisant exactement la conscience de frontière HTTP que le design entier cherche à faire disparaître. La verrue documentée (un `subject` passé par erreur ou par habitude est silencieusement sans effet, jamais signalé) est jugée strictement préférable à une régression de portabilité du code applicatif. L'authentification réelle est déplacée au niveau du transport (A.4) : c'est le serveur, avec son propre sujet décodé depuis le jeton porteur, qui prend la décision d'autorisation — exactement comme pour n'importe quel autre appelant HTTP du même `http_server`.

### A.2 — État de session : fusionné dans `HttpTransport`, pas de composant séparé

Alternative envisagée par le mandat : un composant `BrowserSession` séparé, publié sous son propre nom/interface, ou un simple objet partagé pris en dépendance constructeur par les quatre `Remote*`.

**Décision retenue : fusion dans `HttpTransport`** (`set_token`/`get_token`/`clear_token`), pas de composant séparé. Justification : il n'existe qu'**un seul** transport (un seul backend, même origine) — donc un seul endroit a besoin du jeton. Scinder en deux composants (`BrowserSession` + `HttpTransport`) ajouterait un saut de câblage (`HttpTransport` dépendrait de `BrowserSession` pour lire le jeton à chaque requête) sans aucun gain comportemental observable ; ça multiplierait aussi les composants pour les tests à doubler. Pas de nouvelle interface `api` (respect de la contrainte « ne pas toucher `api`/`core` ») : `HttpTransport` est un composant natif ordinaire, dépendance directe des quatre `Remote*`.

Un flux de connexion (mirroring `permissions_app`'s `LoginService` — voir README.md) appelle `IServiceEndpoint.call("login", "POST", [], {}, {"login", "password"}, None)`, obtient `{"token": ...}` dans `ServiceResult.body`, et pose `transport.set_token(...)` — voir §0bis(d) pour pourquoi c'est `login`, pas `login_cookie`.

### A.3 — URL de base : relative même origine par défaut, `IConfiguration` pour la surcharger

`/api` par défaut (chemin relatif : le client est servi par le même backend qu'il appelle, via un `Host`). Surchargeable par `IConfiguration` (`ycappuccino.api.core`, le composant `Configuration` de `core`, qui lit `conf/config.properties`) sous la clé `client.base_url` — même mécanisme que `hosts` utilise pour `<id>.login`/`<id>.password` : une valeur d'environnement, lue une fois au démarrage, jamais rechargée à chaud. `HttpTransport.start()` lit cette clé ; en son absence (pas d'`IConfiguration` publié, ou clé absente), le défaut `/api` s'applique.

### A.4 — Transport : `HttpTransport`, composant natif, singleton réel injecté

**Décision retenue (la recommandation du mandat) : oui**, `HttpTransport` est un vrai `YCappuccinoComponent`, publié sous son propre nom de classe (comme tout composant natif — `core/README.md`, « Services publiés »), injecté par constructeur dans chacun des quatre `Remote*`. C'est un singleton **réel** garanti par le conteneur Pelix (une seule instance de service par framework), pas une convention de code.

Le fetch bas niveau lui-même est délégué à une interface définie **dans ce dépôt**, `IHttpFetcher(YCappuccinoComponent, ABC)` (`ycappuccino.client.transport`) — pas dans `api` : `describe_component`/`_dependency` (`core/component_factory.py`) traitent tout sous-type de `YCappuccinoComponent` comme un type de dépendance injectable, ce n'est pas réservé aux interfaces déclarées dans `api`. Cette liberté est exploitée pour permettre au test d'intégration réel (§8) de publier un faux `IHttpFetcher` et de faire tourner tout le reste — `RemoteCrud`, `RemoteItemCatalog`, `RemoteServiceEndpoint`, `HttpTransport` lui-même — via le **vrai** framework, en CPython, sans jamais toucher au réseau ni à Pyodide. En production, aucun `IHttpFetcher` n'est publié (dépendance `Optional[IHttpFetcher]`) : `HttpTransport.request()` retombe alors sur l'import paresseux `ycappuccino.client.pyodide_transport.pyodide_transport`, seul endroit du dépôt qui importe `pyodide` (à l'intérieur d'une fonction, jamais au niveau module).

**Piège d'ordonnancement identifié et maîtrisé** : une dépendance `Optional[IHttpFetcher]` non agrégée n'est câblée par `create_factory_module` (`core/component_factory.py`) qu'**au moment de la validation** du composant qui la porte (`HttpTransport`) — il n'y a pas de callback `bind`/`un_bind` pour une dépendance optionnelle simple (seules les collections `list[...]` et les `bind()` de `YCappuccinoComponentBind` en ont un, voir la lecture de `create_factory_module`). Si un faux `IHttpFetcher` de test devient disponible **après** que `HttpTransport` a déjà validé avec `fetcher=None`, il ne sera **jamais** rattrapé. Le test d'intégration (§8) neutralise ce piège en listant le paquet du faux `IHttpFetcher` **avant** `"ycappuccino.client"` dans `bundle_prefix` : `Framework.load_bundles()` installe et valide les bundles paquet par paquet, dans l'ordre de `bundle_prefix` (`core/framework.py`, `load_bundles`/`_import_modules`) — le même principe que `hosts`/`scheduler` utilisent déjà pour garantir qu'un document/tâche de bootstrap existe avant qu'un composant à chargement unique ne le lise (voir leurs README, « Un seul servlet, plusieurs montages » / commentaire de `test_scheduler_framework.py`).

### A.5 — Traduction des erreurs

`ycappuccino.client.transport.decode_envelope(response: RawResponse) -> dict` décode l'enveloppe `{"status", "meta", "data"}` et lève `NotAuthenticated`/`Forbidden`/`NotFound`/`InvalidRequest`/`CrudError` générique selon le statut HTTP — adapté de `remote/call.py::_translate` (lu intégralement), **pas importé** : `client` ne doit pas dépendre de `remote`, dont le modèle d'adressage (un registre `RemoteServer` de pairs nommés, adressés par `extra_path`) ne s'applique pas à un client navigateur qui n'a qu'un seul backend fixe, même origine. La fonction est volontairement plus générale que celle de `remote` : elle ne construit pas de `ServiceResult` (utile uniquement à `RemoteServiceEndpoint`), et sert aux quatre `Remote*`.

## 3. `item_id` → pluriel : résolution par `IItemCatalog`

Vérifié en lisant `http_server/src/main/python/ycappuccino/http_server/servlet.py` (`ApiServlet._route_crud`/`_item_id`), pas seulement le README : les routes sont en pluriel (`/api/crud/<pluriel>[/<id>]`), et `ApiServlet` résout `plural -> item_id` via `self._catalog.get_item_by_plural(plural, subject)["id"]` avant d'appeler `ICrud`. `RemoteCrud`/`RemoteDrafts` ont besoin de la résolution **inverse**, `item_id -> plural`, puisque leurs propres méthodes reçoivent un `item_id` (contrat `ICrud`) mais doivent construire une URL en pluriel.

**Décision retenue** : `RemoteCrud`/`RemoteDrafts` prennent `catalog: IItemCatalog` en dépendance constructeur (dans les faits, l'aussi auto-découvert `RemoteItemCatalog`) et appellent `(await catalog.get_item(item_id))["plural"]` — la vue publique d'un item contient `plural` (`endpoints_storage/README.md`, « Métadonnées : IItemCatalog »). Alternative rejetée : supposer une convention (`item_id + "s"`), incorrecte en général (pluriels irréguliers, `plural` explicitement configurable côté modèle `@Item`) et un couplage implicite fragile. C'est exactement le genre de câblage transversal entre composants pour lequel le vrai conteneur de DI existe — la seule alternative honnête à une convention de nommage fragile.

`RemoteItemCatalog` lui-même récupère `GET /api/items` **une seule fois, à `start()`**, et met en cache la liste par `id`/`plural` — pas de rechargement à chaud, documenté comme simplification délibérée (même précédent que `scheduler`/`hosts`, voir leurs README). `get_schema`/`get_empty` ne font pas partie de cette liste (routes séparées, `/api/items/<pluriel>/schema`/`empty`) et interrogent le réseau à chaque appel, après résolution du pluriel via le cache.

## 4. Emballage : composants navigateur vs. code applicatif hôte

| Partie | Nature | Consommé par |
|---|---|---|
| `ycappuccino.client.transport` (`HttpTransport`, `IHttpFetcher`, `RawResponse`, `decode_envelope`) | composant natif + interface locale, testable en CPython | les quatre `Remote*` |
| `ycappuccino.client.remote_crud`/`remote_drafts`/`remote_item_catalog`/`remote_service_endpoint` | composants natifs, publiés sous `ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint` | auto-découverts par `bundle_prefix`, jamais nommés par le code applicatif |
| `ycappuccino.client.pyodide_transport` | fonction, import `pyodide` paresseux (jamais au niveau module) | `HttpTransport`, uniquement si aucun `IHttpFetcher` n'est publié |
| `client/example/library/{books,catalog}.py` | modèle `@Item` + composant de démo, non empaquetés dans le wheel | démonstration/tests, jamais le wheel `ycappuccino-client` |
| `client/static/{index.html,main.py}` | assets navigateur bruts, servis par un `Host` | jamais exécutés/testés en CPython |

`pyproject.toml` déclare maintenant `ycappuccino-api` **et** `ycappuccino-core` en dépendances `uv` normales (sources locales éditables) : contrairement à la v1, `core.framework`/`core.testing` sont de vraies dépendances d'exécution (le test d'intégration §8 démarre un vrai `Framework`), pas seulement une dépendance transitive inutilisée.

Le bootstrap navigateur (`static/main.py`) `micropip.install(url, deps=False)` quatre wheels, dans l'ordre : `iPOPO`, `ycappuccino-api`, `ycappuccino-core`, `ycappuccino-client` — après `pyodide.loadPackage("pyyaml")` (§0bis(b)). `deps=False` reste nécessaire (la déclaration `iPOPO>=3.0` d'`api` n'est pas conditionnée), mais **iPOPO lui-même doit désormais être installé** (contrairement à la v1, qui ne le chargeait jamais) : c'est la brique la plus risquée de toute la chaîne, sa compatibilité Pyodide n'étant vérifiée nulle part dans ce dépôt.

## 5. Modèles partagés (inchangé)

`example/library/books.py` : `Book(Model)`, `@Item(collection="books", name="book", plural="books")`, n'important que `ycappuccino.api.decorators`/`ycappuccino.api.models` (sous-ensemble import-clean, §0). `example/library/catalog.py` (nouveau) : `Catalog(YCappuccinoComponent)`, dépendant de `crud: ICrud`/`catalog: IItemCatalog` — jamais de `ycappuccino.client` — qui peuple `self.items` à `start()`. C'est la preuve, par composition réelle et non par une fonction de test isolée, que le câblage bout en bout fonctionne.

## 6. Bootstrap navigateur : `static/index.html` + `static/main.py`

Séquence complète (voir README.md pour le détail commenté) : Pyodide chargé sur une page COOP/COEP (Partie C) avec un build pthread (§0bis(a), non vérifié) → `pyodide.loadPackage("pyyaml")` (§0bis(b)) → `micropip.install(..., deps=False)` × 4 (§4) → écriture de `conf/application.yml` + du paquet de démo dans le FS virtuel (§0bis(c)) → `Framework().init("conf/application.yml")` → lecture du service résolu par DI (`framework.context.get_service_reference("Catalog")`) → rendu DOM minimal.

**Rien de cette séquence n'a été exécuté dans ce bac à sable.** Marqué vérification manuelle requise, sans exception, dans le code (`static/main.py`, commentaires de tête et inline) et dans le README.

## 7. Fichiers

```
client/
  pyproject.toml
  README.md
  docs/superpowers/specs/2026-09-15-client-design.md
  docs/superpowers/plans/2026-09-15-client.md
  src/main/python/ycappuccino/client/
    __init__.py
    transport.py                    # HttpTransport, IHttpFetcher, RawResponse, decode_envelope
    pyodide_transport.py            # pyfetch, import pyodide paresseux
    remote_crud.py                  # RemoteCrud(ICrud)
    remote_drafts.py                # RemoteDrafts(IDrafts)
    remote_item_catalog.py          # RemoteItemCatalog(IItemCatalog)
    remote_service_endpoint.py      # RemoteServiceEndpoint(IServiceEndpoint)
  src/unittest/python/
    fake_fetcher.py, fake_catalog.py
    test_transport.py
    test_remote_crud.py, test_remote_drafts.py, test_remote_item_catalog.py, test_remote_service_endpoint.py
    test_client_framework.py        # vrai Framework, vrai bundle_prefix incluant ycappuccino.client
    test_models.py, test_readme.py
  example/library/
    __init__.py, books.py, catalog.py
  static/
    index.html, main.py
```

## 8. Tests : ce qui est réellement prouvé

- **Unitaire, par composant, sans framework** (`test_transport.py`, `test_remote_*.py`) : chaque `Remote*`/`HttpTransport` construit directement avec un faux `IHttpFetcher`/une fausse `IItemCatalog`, aucune dépendance à Pyodide ni au réseau — même style que `test_http.py` en v1, adapté à la nouvelle forme des composants.
- **Intégration, vrai framework** (`test_client_framework.py`) : `Framework()` réel, `bundle_prefix: [PACKAGE, "ycappuccino.client"]` — **`ycappuccino.client` lui-même**, jamais une construction manuelle de `RemoteCrud`/etc. — plus un composant `Demo` de l'application de test dépendant de `ICrud`/`IItemCatalog`/`IServiceEndpoint` avec **zéro** référence à `ycappuccino.client`. Seul le tout dernier maillon (l'appel HTTP bas niveau) est remplacé, par un faux `IHttpFetcher` publié dans `PACKAGE` (listé avant `ycappuccino.client`, §2 A.4). C'est la preuve la plus forte possible sans navigateur réel : la résolution DI complète (`ICrud`/`IItemCatalog`/`IServiceEndpoint` → `RemoteCrud`/`RemoteItemCatalog`/`RemoteServiceEndpoint`, elles-mêmes dépendant du vrai `HttpTransport`) fonctionne réellement dans le vrai Pelix/iPOPO.
- **`test_readme.py`** : rejoue les exemples du README exécutables en CPython (composant `Catalog`/`Login` câblés à la main avec de faux transports, round-trip `Book`).
- **Non prouvé, ne pouvant pas l'être ici** : tout ce qui touche à un vrai Pyodide/navigateur — §0bis in extenso.

## 9. v3 : `make_remote`, fabrique générique par réflexion

### 9.0 Ce qui ne change pas

`HttpTransport`, `IHttpFetcher`, `RawResponse`, `decode_envelope` (§2 A.4/A.5) : inchangés, réutilisés tels quels. La décision « `subject` conservé mais ignoré » (§2 A.1) : inchangée. L'URL de base via `IConfiguration` (§2 A.3) : inchangée. L'ergonomie applicative (§1, §3) : inchangée — `bundle_prefix: ycappuccino.client` suffit, le code applicatif ne dépend que d'`ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint`.

### 9.1 Ce qui change : une fabrique, pas quatre classes

`ycappuccino.client.remote_proxy.make_remote(interface: type, resource: str, **extra_deps: type) -> type` synthétise, par réflexion sur `interface` (une interface `YCappuccinoComponent` abstraite), une classe concrète implémentant chacune de ses méthodes abstraites — **aucune méthode n'est écrite à la main, aucune table `{(interface, méthode): (verbe, gabarit de chemin)}` n'existe où que ce soit dans ce dépôt.** Tout est dérivé, à la construction de la classe ou à l'appel, du **nom de la méthode** et des **noms de ses paramètres** — un petit vocabulaire fixe et générique (`item_id`, `id`, `draft`, `filter`, `fields`/`body`, `params`, `subject`, `method`, `extra_path`), pas une liste de routes.

`ycappuccino/client/components.py`, un module ordinaire du paquet, scanné comme n'importe quel autre par `Framework.load_bundles()` :

```python
RemoteCrud = make_remote(ICrud, "crud", catalog=IItemCatalog)
RemoteDrafts = make_remote(IDrafts, "drafts", catalog=IItemCatalog)
RemoteItemCatalog = make_remote(IItemCatalog, "items")
RemoteServiceEndpoint = make_remote(IServiceEndpoint, "services")
```

**Exception assumée, minimale et délibérée à « zéro donnée par interface » : le préfixe de montage HTTP (`resource`)**, un seul mot par appel (`"crud"`, `"drafts"`, `"items"`, `"services"`). Ce n'est **pas** une table de routes par méthode (ce que l'utilisateur a rejeté) : c'est un unique fait de déploiement — le préfixe de montage HTTP d'une interface entière — qu'aucune réflexion sur les noms de méthodes/paramètres ne peut dériver de façon fiable (`ICrud`/`IItemCatalog`/`IServiceEndpoint` n'ont, par construction, aucun lien textuel entre leur nom de classe et `"crud"`/`"items"`/`"services"`). Documenté ici explicitement comme le seul renoncement à la pureté totale de la réflexion, et pourquoi il est catégoriquement différent de ce qui a été rejeté.

### 9.2 Signature réelle et introspectable du constructeur synthétisé (exigence critique)

`describe_component`/`_constructor_parameters` (`core/component_factory.py`) lisent `inspect.signature(klass.__init__)` et `typing.get_type_hints(klass.__init__)` **par nom de paramètre et annotation de type** : un `__init__(self, **kwargs)` générique ne serait **pas** reconnu comme un composant injectable valide (aucun paramètre nommé/typé à câbler). `make_remote` construit donc le vrai `__init__` par génération de code source (`exec`, la même technique que `dataclasses`/`attrs`/`collections.namedtuple` utilisent pour forger un constructeur au nom et à la signature réels) :

```python
source = f"def __init__(self, transport: _T_transport, {', '.join(f'{n}: _T_{n}' for n in extra_deps)}):\n    self._transport = transport\n" + "".join(f"    self._{n} = {n}\n" for n in extra_deps)
namespace = {"_T_transport": HttpTransport, **{f"_T_{n}": t for n, t in extra_deps.items()}}
exec(source, namespace)
```

Les annotations (`_T_transport`, `_T_<nom>`) sont des expressions Python ordinaires dans la ligne `def`, évaluées par l'interpréteur au moment de la définition — `__annotations__` est donc peuplé nativement avec les **vrais objets de type** (`HttpTransport`, `IItemCatalog`, jamais des chaînes), exactement ce que `typing.get_type_hints` attend. **Vérifié contre le vrai `describe_component`/`create_factory_module`, pas supposé** : `test_client_framework.py` (conservé, mêmes assertions qu'en v2) prouve que le vrai conteneur Pelix/iPOPO résout `transport`/`catalog` sur la classe synthétisée exactement comme sur une classe écrite à la main.

Autre détail nécessaire pour que le scan de `Framework._install_module` (qui filtre `klass.__module__ == module.__name__`) découvre la classe synthétisée : `make_remote` lit le nom du module appelant via `sys._getframe(1).f_globals["__name__"]` et l'assigne explicitement à `namespace["__module__"]` avant `type(...)`. **Limite honnête** : ceci repose sur `sys._getframe`, un détail d'implémentation CPython (bien qu'utilisé couramment par des bibliothèques stdlib/tierces pour la même raison) — non garanti sur tout interpréteur Python, non vérifié sous Pyodide spécifiquement (aucune raison connue d'en douter, Pyodide étant une build CPython, mais non testé ici).

**Découverte réelle, pas hypothétique, faite en écrivant `test_client_framework.py`** : la première version de ce test publiait un faux `ycappuccino.client.transport.IHttpFetcher` depuis un paquet temporaire listé avant `ycappuccino.client` dans `bundle_prefix` — exactement le mécanisme que la docstring d'`IHttpFetcher` recommandait initialement. **Il échouait de façon déterministe** (confirmé par instrumentation directe de `HttpTransport.__init__` : `fetcher=None` à chaque exécution), alors même que le faux service était indépendamment confirmé présent et trouvable dans le registre Pelix (`context.get_service_reference("IHttpFetcher")`) au moment exact de la construction de `HttpTransport`. Isolé par élimination (reproductions minimales avec une paire fournisseur/consommateur `Optional[IThing]` écrite à la main) : le bug ne se reproduit **que** lorsque le consommateur (`HttpTransport`) vit dans le paquet-espace-de-noms `ycappuccino.*` pendant que le fournisseur vit dans un paquet de test temporaire — **exactement** le défaut déjà documenté dans la docstring de `hosts/src/main/python/ycappuccino/hosts/servlet.py` : « an optional dependency satisfied elsewhere in the same multi-path "ycappuccino.*" namespace package was observed to resolve non-deterministically (sometimes None) depending on scan timing ». Le correctif de `hosts` (rendre la dépendance obligatoire) n'est pas disponible ici (`HttpTransport` doit pouvoir démarrer sans fetcher en déploiement réel). **Correctif retenu** : `test_client_framework.py` ne publie plus de composant `IHttpFetcher` du tout — il remplace directement, par une simple affectation Python (`pyodide_transport_module.pyodide_transport = fake_function`), la fonction de repli que `HttpTransport.request()` importe paresseusement à chaque appel (`from ycappuccino.client.pyodide_transport import pyodide_transport`) — une lecture d'attribut de module ordinaire, protégée par le GIL, sans aucune temporalité du registre de services Pelix en jeu. `IHttpFetcher` reste dans le code comme point d'extension documenté (et reste exercé, en toute sécurité, par `test_transport.py`, entièrement en-process, sans Pelix), mais sa fiabilité **au travers d'une frontière de paquet-espace-de-noms `ycappuccino.*`** n'est prouvée nulle part dans ce dépôt — voir §9.4.

### 9.3 Les cinq conventions (verbatim — à respecter exactement, y compris leurs limites)

**Convention 1 — verbe HTTP inféré du nom de la méthode :**

| Nom (préfixe/exact) | Verbe |
|---|---|
| commence par `get` | `GET` |
| `update`, `save` | `PUT` |
| commence par `delete`, ou `discard` | `DELETE` |
| tout le reste (`create`, `publish`, toute action future non reconnue) | `POST` |

**Convention 2 — construction du chemin, à partir des noms de paramètres (dans leur ordre de déclaration) :**

| Nom de paramètre | Effet |
|---|---|
| `item_id` | résolu en pluriel (voir ci-dessous) et ajouté comme segment |
| `id`, `draft` | valeur ajoutée telle quelle comme segment (dans cet ordre de déclaration : `id` avant `draft` pour `IDrafts`, ce qui tombe automatiquement juste car l'ordre des paramètres de l'interface l'est déjà) |
| `filter` | envoyé en **query string** (`?filter=...`), jamais dans le corps — vérifié contre `ApiServlet._route_crud` : `delete_many` lit `params.get("filter")`, pas le corps JSON |
| `fields`, `body` | envoyé comme corps JSON |
| `params` | fusionné directement dans la query string (déjà un dict de la forme attendue par le serveur) |
| `subject` | ignoré (§2 A.1), jamais transmis |
| tout autre nom simple (en pratique : `name` d'`IServiceEndpoint.call`) | valeur ajoutée telle quelle comme segment, dans l'ordre de déclaration |

Puis un **suffixe** est ajouté selon le verbe et si le nom de méthode fait partie de l'ensemble « standard » `{get_one, get_many, get_items, create, update, delete, delete_many, save}` :
- nom standard, **ou** verbe `DELETE`/`PUT` → pas de suffixe (`delete`/`delete_many`/`discard` sont désambiguïsés par le verbe et la forme des arguments seuls, jamais par un segment `.../discard` — **vérifié contre le vrai `ApiServlet._route_drafts`**, qui n'a pas de segment `discard` dans sa route : `DELETE /api/drafts/<pluriel>/<id>/<brouillon>`, identique à celle de `save`/`get_one`, seul le verbe diffère) ;
- sinon, verbe `GET` → le nom de méthode privé de son préfixe `get_` (`get_schema` → `.../schema`, `get_empty` → `.../empty`) ;
- sinon (verbe `POST`) → le nom de méthode complet (`publish` → `.../publish`, vérifié contre la vraie route `POST /api/drafts/<pluriel>/<id>/<brouillon>/publish`).

**Convention 3 — dérogation littérale pour une méthode « déjà HTTP-shaped » (`IServiceEndpoint.call`, et génériquement toute méthode future de même forme) :** le **déclencheur** est la présence, par nom exact, d'un paramètre `method` **ou** `extra_path` — les deux seuls noms de tout le vocabulaire qui ne sont *jamais* utilisés génériquement ailleurs (contrairement à `params`/`body`, qu'`ICrud`/`IDrafts` utilisent aussi, avec un sens différent — un paramètre `params`/`body` seul, sans `method` ni `extra_path`, ne déclenche donc **pas** cette convention : bogue réel rencontré et corrigé pendant l'implémentation, voir §9.4). Une fois déclenchée, les **valeurs d'exécution** de `method`/`extra_path`/`params`/`body` (ceux qui sont présents) sont utilisées directement — `method` devient le verbe (au lieu d'être inféré du nom de la méthode), `extra_path` une liste de segments ajoutés en fin de chemin, `params`/`body` la query/le corps — et les conventions 1/2/4 ne s'appliquent plus du tout à cette méthode. Ce n'est **pas** un cas spécial d'`IServiceEndpoint` en soi : c'est une convention nommée et générique (« une méthode qui porte déjà le verbe/chemin en paramètres explicites n'a besoin d'aucune inférence »), qui se trouve n'être déclenchée aujourd'hui que par cette seule interface.

**Convention 4 — mise en cache d'une collection complète (`IItemCatalog`, et génériquement toute interface de même forme) :** une méthode `get_*` dont **tous** les paramètres (hors `self`) ont une valeur par défaut (aucun argument requis) est la **méthode d'accès à la collection** : son GET HTTP n'est déclenché **qu'une seule fois**, à `start()`, et mis en cache pour la durée de vie du composant (pas de rechargement à chaud, même convention que `scheduler`/`hosts`). Un **mot-clé d'identité** est dérivé du nom de cette méthode (préfixe `get_` retiré, `s` finale retirée : `get_items` → `item`) — dérivation naïve, documentée comme fragile (ne généralise pas à un pluriel irrégulier). Toute **autre** méthode `get_*` de la **même** interface dont le reste du nom (après `get_`) est exactement ce mot-clé, ou commence par `<mot-clé>_by_<champ>`, est résolue **sans requête HTTP**, par une recherche dans la collection déjà en cache : `get_item(item_id)` → cherche `id == item_id` ; `get_item_by_plural(plural)` → cherche `plural == plural` (le nom du champ, `plural`, est extrait du nom de la méthode elle-même, jamais codé en dur). **Toute autre méthode `get_*` qui ne correspond pas à ce test (`get_schema`, `get_empty` : leur reste-de-nom, `schema`/`empty`, ne commence pas par `item`) suit la convention 2 normalement** — chemin HTTP réel, une requête par appel, avec l'`item_id` résolu via cette même collection en cache (voir résolution `item_id → pluriel` ci-dessous).

**Limite honnête, non contournable par la seule réflexion sur les noms** : rien dans cette convention ne permettrait de distinguer `get_item(item_id)` (recherche en cache) de `get_schema(item_id)`/`get_empty(item_id)` (appel HTTP réel) si elles avaient été nommées différemment — la distinction ne fonctionne **que parce que** `get_schema`/`get_empty` ne commencent pas, une fois `get_` retiré, par le mot-clé d'identité `item`. Une interface hypothétique avec une méthode `get_item_summary(item_id)` (qui devrait être un appel HTTP, comme `get_schema`) serait **incorrectement** traitée comme une recherche en cache par cette règle, puisque son reste-de-nom `item_summary` commence par `item`. **Ceci est un vrai point faible de l'approche par réflexion pure, accepté sciemment** : la table déclarative rejetée n'aurait pas eu ce problème.

**Résolution `item_id → pluriel`** (utilisée par les conventions 2 et 4) : si la classe synthétisée a une dépendance `extra_deps` nommée littéralement `catalog` (cas de `RemoteCrud`/`RemoteDrafts`), résolution via `await self._catalog.get_item(item_id)`. Sinon, si l'instance a sa **propre** collection en cache (convention 4 — cas de `RemoteItemCatalog` lui-même, qui n'a pas de dépendance `catalog` externe), résolution par recherche dans son propre cache. Sinon, `RuntimeError` explicite (câblage manquant).

**Convention 5 — forme du résultat, dérivée du nom de la méthode :** `get_many` → `{"items": data, "total": meta["size"]}` (pagination, comme `ICrud`/`IDrafts` le documentent) ; `delete_many` → `data["deleted"]` (entier) ; `delete`/`discard` → `None` ; une méthode couverte par la convention 3 (dérogation littérale) → `ServiceResult(body=data)` ; toute autre méthode → `data` brut de l'enveloppe.

### 9.4 Limites honnêtes — où la réflexion pure tient, où elle est plus fragile qu'une table déclarative

- **`get_item_summary`-like** (convention 4) : voir ci-dessus — un nom de méthode `get_*` mal choisi sur une future interface pourrait être mal routé sans qu'aucun test unitaire de ce dépôt ne puisse le prédire à l'avance (seuls les quatre interfaces réellement présentes dans `api` aujourd'hui sont vérifiées, exhaustivement, par les tests).
- **`sys._getframe`** (§9.2) : détail d'implémentation CPython, non vérifié sous Pyodide.
- **`IHttpFetcher` au travers d'une frontière de paquet-espace-de-noms `ycappuccino.*`** (§9.2) : découvert cassé, pas juste suspecté — un `Optional[IHttpFetcher]` publié depuis un paquet applicatif différent de `ycappuccino.client` ne se câble pas de façon fiable ; seul le cas « même paquet » ou « hors espace de noms `ycappuccino.*` » a été vérifié fonctionnel. `test_client_framework.py` contourne le problème (repli sur `pyodide_transport` remplacé directement, sans DI) plutôt que de le résoudre : le mécanisme `IHttpFetcher` lui-même reste fragile pour un usage applicatif réel dans ce contexte précis.
- **Singularisation naïve** (`items` → `item`) : ne généralise pas à un pluriel irrégulier (`children` → ne donnerait pas `child`).
- **Le préfixe `resource`** (§9.1) reste une donnée par interface, minimale mais réelle — la réflexion n'est pas *totale*, seulement quasi totale.
- **Lisibilité** : un développeur qui lit `remote_proxy.py` seul, sans lire ce §9, ne peut pas deviner qu'un appel à `RemoteDrafts.publish(...)` produit `POST .../publish` sans dérouler mentalement les cinq conventions — une table déclarative aurait été strictement plus lisible au prix de plus de code répété. Compromis assumé, demandé explicitement par l'utilisateur.

Ce qui **tient bien**, vérifié exhaustivement (un test par méthode des quatre interfaces, verbe/chemin/corps/query exacts asserés) : les six méthodes d'`ICrud`, les cinq d'`IDrafts` (y compris la distinction `discard` sans suffixe / `publish` avec suffixe, la partie la plus piégeuse), les cinq d'`IItemCatalog` (cache vs HTTP réel), et `IServiceEndpoint.call` (dérogation littérale).

## 10. v4 (2026-09-16) — découverte des composants du backend, création des proxys au vol

Demande explicite de l'utilisateur, après une troisième clarification avec le coordinateur : chaque `core` doit produire la liste de ses composants embarqués (`Framework.get_framework().list_components()`, ajouté côté `core`, voir `core/README.md` « Introspecter les composants natifs installés ») ; `remote` doit pouvoir interroger cette liste par pair (travail en cours, en parallèle, dans le dépôt `remote` — jamais touché ici) ; et `client` doit lui aussi interroger le backend et créer ses proxys **au vol**, plutôt qu'une table fixe de quatre. Le coordinateur a présenté deux options à l'utilisateur (réduite : ne proxy que les quatre interfaces déjà connues, en sautant celles absentes ; totalement générique : proxy n'importe quelle interface découverte, y compris une interface applicative sur mesure). **L'utilisateur a choisi explicitement l'option totalement générique.**

### 10.0 Ce qui ne change pas

Tout le §9 reste valide tel quel : `make_remote`, ses cinq conventions, `HttpTransport`/`IHttpFetcher`/`decode_envelope`. `ycappuccino/client/components.py` **continue d'exister et de fonctionner exactement comme avant** — c'est désormais le repli explicite (§10.1) quand la découverte est indisponible, pas un code mort. Seul changement non comportemental dans ce fichier : les quatre `make_remote(...)` sont maintenant produits par une boucle sur `known_interfaces.KNOWN_INTERFACES` plutôt qu'écrits quatre fois — mêmes classes, mêmes noms, même ordre, vérifié par la suite de tests préexistante inchangée (55 tests toujours verts avant tout ajout).

### 10.1 Question 1 — `client` peut-il découvrir la liste du backend à distance, et comment ?

**Résolu honnêtement, pas de contrat propre : uniquement par convention.** `Framework.list_components()` est une pure API Python côté `core`, non câblée sur aucun transport par le travail de l'agent `core` — rien dans `http_server`/`endpoints_service` n'expose cette liste aujourd'hui, et `http_server` est explicitement hors périmètre ici (ne pas y toucher). La seule ouverture existante : **si** le backend charge par ailleurs `ycappuccino.remote` (en cours d'extension, en parallèle, pour exposer une capacité élargie — probablement nommée `__remote_capabilities__` par convention, pas par coordination directe avec cet agent), ce service serait appelable **sans aucun code spécial** via la route déjà générique `/api/services/<nom>`, exactement comme n'importe quel service nommé — `RemoteServiceEndpoint`/`IServiceEndpoint.call` n'a besoin d'aucune modification pour appeler un service dont il ignore tout à l'avance.

`ycappuccino.client.discovery.discover_backend_provides()` tente donc, au démarrage, `IServiceEndpoint.call("__remote_capabilities__", "POST", [], {}, {}, subject=None)` — construit à la main (`HttpTransport` + le proxy `IServiceEndpoint` synthétisé par `make_remote`, sans Pelix ni DI, exactement le style des tests unitaires par composant de ce dépôt, voir `core/README.md` « Tester ses composants »). **Si l'appel échoue, pour N'IMPORTE QUELLE raison** (`NotFound` parce que le backend ne charge pas `ycappuccino.remote` ou n'a pas câblé ce nom précis, erreur réseau, réponse mal formée) : résultat `None`, traité comme « inconnu », et repli intégral sur le comportement historique inconditionnel des quatre interfaces (§10.3).

**Ceci est un couplage réel, non documenté ailleurs que par convention, entre `client` et ce que le backend charge par ailleurs** : `client` n'importe pas `ycappuccino.remote`, ne connaît pas sa forme exacte, et cet agent n'a aucune autorité sur ce que l'agent de `remote` livre réellement. Si ce nom ou la forme supposée de la réponse changent, la découverte se dégrade silencieusement vers le repli — c'est le comportement voulu, pas un bug à masquer. La forme supposée de la réponse (`_extract_provides`) est elle-même une hypothèse non vérifiée contre une implémentation réelle de `remote` : une liste de `{"module", "class", "provides"}`, identique à `list_components()` elle-même — la forme la plus plausible pour un service qui renverrait `Framework.get_framework().list_components()` tel quel, mais une **hypothèse**, pas un contrat.

### 10.2 Question 2 — comment éviter le piège de timing documenté par `core` ?

`core/README.md` documente précisément le piège (« Piège de timing ») : créer un composant depuis le `start()` d'un autre, même en tâche de fond (comme `ycappuccino-component-creator`'s `ComponentActivator.start()`), ne garantit **aucunement** que l'instance existe avant la fin de la même passe de scan `bundle_prefix` — un autre composant natif scanné dans la même passe, avec une dépendance **obligatoire** sur l'interface concernée, peut très bien ne jamais la voir apparaître à temps.

**Option envisagée et écartée : reproduire l'approche de `remote`** (découverte + `instantiate_component()` déclenché depuis le `start()` d'un composant, en tâche de fond) — c'est ce à quoi l'agent de `remote` est contraint, parce qu'un paquet scanné par `bundle_prefix` est un scan Python statique et synchrone, sans I/O possible avant que `load_bundles()` ne tourne. **`client` n'a pas cette contrainte** : son bootstrap (`static/main.py`) est du code entièrement maîtrisé par ce dépôt, qui fait déjà de l'async (Pyodide/micropip, écriture dans le système de fichiers virtuel) **avant** d'appeler `Framework().init()`.

**Option retenue : découverte-puis-génération-de-code, avant `init()` (« codegen-before-init »).** `discovery.py` transforme la question dynamique (« quelles interfaces le backend a-t-il ? ») en un fait statique, écrit sur disque **avant** que le framework n'existe :

1. `discover_backend_provides()` — voir §10.1 — renvoie l'ensemble des chemins qualifiés `provides` du backend, ou `None`.
2. `enabled_known_interfaces(discovered)` — `None` → repli intégral, les quatre interfaces connues (`known_interfaces.KNOWN_INTERFACES`, inchangé) ; sinon, résout chaque chemin qualifié en une vraie classe via `ycappuccino.core.component_factory.resolve_class` (**la même fonction que `core/README.md` documente explicitement pour cet usage** — nouvelle dépendance de `client` vers `core.component_factory`, `ycappuccino-core` étant déjà une dépendance `uv` normale de ce dépôt depuis la v2, voir §4 — aucune ligne de `pyproject.toml` à ajouter), et ne garde que les interfaces connues effectivement présentes.
3. `write_generated_module(enabled, file_path)` écrit un module Python **ordinaire**, de forme strictement identique à `components.py` (mêmes imports, mêmes appels `make_remote(...)`) — voir `generated_module_source()`. Rien de dynamique ne se produit *pendant* ni *après* le scan `bundle_prefix` : ce module est un fichier source statique comme un autre au moment où `Framework.load_bundles()` le découvre.
4. Le `bundle_prefix` de l'application liste ce module généré **à la place de** `"ycappuccino.client"` (dont `components.py`, le repli inconditionnel, ferait sinon doublon et entrerait en collision avec le sous-ensemble découvert) — `discovery.without_client_components()` fait cette substitution : `"ycappuccino.client"` → `"ycappuccino.client.transport"` (seul `HttpTransport`, jamais conditionnel, reste nécessaire de ce paquet).

**Conséquence directe : aucun appel à `instantiate_component()`/`destroy_component()` n'existe nulle part dans ce mécanisme.** Le piège de timing documenté par `core` ne s'applique tout simplement pas ici — pas parce qu'il a été neutralisé avec précaution, mais parce que la construction entière n'emprunte jamais ce chemin. C'est un choix jugé **structurellement plus sûr**, spécifique à la forme du bootstrap navigateur de ce dépôt, et non disponible à `remote` pour son propre cas (pairs déjà en cours d'exécution, pas de fenêtre « avant l'existence du framework » équivalente).

**Piège d'ordonnancement réel, découvert en écrivant `test_client_discovery_framework.py`, pas hypothétique** : `Framework.load_bundles()` installe les entrées de `bundle_prefix` **paquet par paquet, dans l'ordre** (`core/README.md`, comportement déjà invoqué au §9.2 pour le bug `IHttpFetcher`). Deux contraintes d'ordre, vérifiées empiriquement contre le vrai framework :
- `"ycappuccino.client.transport"` (`HttpTransport`) doit précéder le module généré : les `Remote*` ont une dépendance **obligatoire** (non optionnelle) sur `HttpTransport` — listée après, aucun `Remote*` ne valide jamais (silencieusement : ni exception, ni service, iPOPO attend indéfiniment un fournisseur dont le bundle n'est même pas encore installé).
- le module généré doit précéder tout module applicatif qui dépend directement (non optionnellement) de `ICrud`/`IItemCatalog` (comme `example/library/catalog.py`'s `Catalog`) — même raison.
- écrire le module généré comme un module **de premier niveau** (pas imbriqué dans un paquet applicatif) évite une troisième source d'incertitude : l'ordre *interne* du scan `pkgutil.walk_packages` d'un paquet n'est pas documenté comme garanti, contrairement à l'ordre *entre* les entrées de `bundle_prefix`, qui l'est.

Un premier essai de test intégrait ces classes directement dans le composant `Demo` applicatif via des dépendances `Optional[ICrud]`/etc. pour distinguer « créé » de « non créé » : **découverte réelle, pas anticipée** — ce test s'est révélé authentiquement instable, parce qu'un composant sans aucune dépendance obligatoire peut valider (et capturer, une fois pour toutes, ses dépendances optionnelles alors `None`) **avant** que la chaîne `RemoteCrud → RemoteItemCatalog` n'ait fini de se résoudre, sans jamais être re-sollicité ensuite (une dépendance optionnelle simple n'a pas de callback `bind`/`un_bind`, voir §9.2). Le test définitif interroge directement le registre Pelix (`context.get_service_reference(nom)`, avec `wait_until`) plutôt que l'injection applicative — ce n'est plus sujet à cette course.

### 10.3 La vraie frontière du « totalement générique »

L'utilisateur a choisi l'option totalement générique ; **ce choix se heurte à une limite réelle, pas contournable depuis `client` seul**, qu'il faut énoncer sans l'édulcorer.

`make_remote(interface, resource, **extra_deps)` a structurellement besoin de `resource` — le préfixe de montage HTTP à un seul mot (`"crud"`, `"drafts"`, `"items"`, `"services"`) — et **rien dans la réflexion sur les noms de méthodes/paramètres d'une interface ne permet de le déterminer** (§9.1, inchangé). Cette information n'existe, aujourd'hui, que pour quatre interfaces : celles pour lesquelles `http_server` a effectivement codé une route REST (`ApiServlet._route_crud`/`_route_drafts`/etc.). Une interface applicative arbitraire, même parfaitement découverte via `__remote_capabilities__` (nom qualifié, module, tout), **n'a tout simplement aucune forme HTTP connue de `client`** — il n'existe nulle part de route générique `/api/rpc/<interface>/<méthode>` que `client` pourrait appeler à l'aveugle.

C'est très différent du cas de `remote` (pairs serveur-à-serveur) : les deux extrémités y sont des processus Python capables de faire tourner un dispatcher RPC générique (appeler une méthode par son nom sur un objet distant, sans connaître sa route HTTP à l'avance — parce qu'il n'y a pas de route HTTP du tout, juste un appel de méthode sérialisé). Un navigateur appelant l'API REST d'`http_server` n'a pas cette option : il n'existe, aujourd'hui, que quatre montages HTTP concrets, point.

**Ce qui est donc réellement construit ici** (§10.2, point 3) :
- (a) création **conditionnée par la découverte** des quatre interfaces connues — un vrai progrès mesurable sur le comportement inconditionnel d'hier (sauter entièrement `RemoteDrafts` si le backend n'a pas `IDrafts`, prouvé par `test_client_discovery_framework.py`) ;
- (b) `known_interfaces.KNOWN_INTERFACES` rend cette table **triviale à étendre** — un unique tuple `(interface, resource, extra_deps)`, une seule ligne à ajouter le jour où une vraie cinquième interface `api` obtient un montage HTTP réel côté `http_server` — au lieu de deux endroits à maintenir en synchronisation (`components.py` et `discovery.py` la consomment désormais tous les deux, au lieu de chacun sa propre copie).

**Ce qui n'est PAS construit, et ne peut PAS l'être depuis `client` seul** : la création de proxy pour une interface applicative arbitraire, sans montage HTTP connu. `enabled_known_interfaces()` élimine silencieusement toute spécification découverte hors de `KNOWN_INTERFACES`, précisément pour cette raison. **Le vrai suivi légitime, non construit ici** : `http_server` devrait grandir une route RPC générique (symétrique de ce que le dispatcher pair-à-pair de `remote` sait déjà faire), ce qui est un changement de fondation hors du périmètre de cet agent (`http_server` explicitement non modifiable ici) — noté comme dette honnête, pas comme un « fully generic » atteint en douce.

### 10.4 Fichiers ajoutés

```
client/src/main/python/ycappuccino/client/
  known_interfaces.py       # KNOWN_INTERFACES, table unique (interface, resource, extra_deps)
  discovery.py               # discover_backend_provides, enabled_known_interfaces,
                              # generated_module_source/write_generated_module,
                              # without_client_components, prepare_generated_module
client/src/unittest/python/
  test_discovery.py                     # unitaire, sans framework
  test_client_discovery_framework.py    # vrai Framework, deux scénarios (sous-ensemble / repli)
```
`components.py` : modifié (boucle sur `KNOWN_INTERFACES`, comportement inchangé). `static/main.py` : la découverte tourne avant `Framework().init()`, écrit `bundle/generated_remote.py`, et `bundle_prefix` référence ce module + `ycappuccino.client.transport` au lieu de `ycappuccino.client` — non exécutable/vérifiable dans ce bac à sable, comme le reste de ce fichier.
