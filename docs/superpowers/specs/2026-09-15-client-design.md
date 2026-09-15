# client navigateur : design (v2 — remplace la conception « ApiClient »)

Date de la conception initiale : 2026-09-15. **Révision du 2026-09-16** : refonte complète, demandée explicitement par l'utilisateur après rejet de la première approche (un `ApiClient` HTTP bespoke). Nouvelle ambition, assumée avec ses risques : **le navigateur charge le vrai `ycappuccino.core.framework.Framework`** (vrai Pelix/iPOPO), et le code applicatif dépend des vraies interfaces `ICrud`/`IDrafts`/`IItemCatalog`/`IServiceEndpoint` (`ycappuccino.api.endpoints_storage`/`endpoints_service`), avec une implémentation « remote » de chacune (HTTP/`fetch`) injectée dessous par le même conteneur de DI que côté serveur — le code applicatif ne sait jamais qu'un appel traverse une frontière HTTP. C'est ce que le dépôt `remote` fait déjà pour les appels serveur-à-serveur (`RemoteCall implements IExposedService`), étendu au navigateur et au CRUD.

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
