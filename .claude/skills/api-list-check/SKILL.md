---
name: api-list-check
description: Monatliche Prüfung der API-Liste (api_list.json) auf tote oder veränderte Links und auf inhaltliche Fehler. Behebt eindeutige URL-Änderungen automatisch, meldet alles andere in einem Bericht unter reports/. Verwende diesen Skill, wenn api_list.json geprüft, aktualisiert oder auf Aktualität kontrolliert werden soll, auch bei Formulierungen wie „Links checken“, „API-Liste auf den neuesten Stand bringen“ oder „monatlicher Check“.
---

# api-list-check

`api_list.json` ist die Datenquelle der Website (GitHub Pages). Die Einträge veralten: Dokumentationen ziehen um, Limits und Lizenzen ändern sich, APIs werden abgeschaltet. Dieser Skill prüft die Liste und hält sie aktuell, ohne dass inhaltliche Texte unbemerkt verändert werden.

## Grundsätze

- **Eindeutiges darf automatisch korrigiert werden, Inhaltliches nicht.** Eine URL, die dauerhaft (301/308) auf dieselbe Seite derselben Domain umzieht, ist eindeutig. Ob sich ein Rate-Limit geändert hat, ist eine Aussage, die ein Mensch bestätigen sollte – die Texte sind zweisprachig (en/de) und von Hand formuliert.
- **Nichts committen oder pushen.** Das erledigt Nobu selbst. Der Bericht sagt, was zu committen ist.
- **Vor jeder Änderung an `api_list.json` ein Backup anlegen.** Das gilt für die automatischen Korrekturen (Schritt 4) ebenso wie für später freigegebene Textänderungen. Ablage: `backup/api_list_YYYYMM.json` (Monat der Prüfung; existiert die Datei schon, `-2` anhängen). Nie ein vorhandenes Backup überschreiben.
- **Nur `api_list.json`, `reports/` und `backup/` anfassen.** `reports/` steht nicht mehr in `.gitignore`, weil Nobu die Berichte mit Kolleginnen und Kollegen teilt; ob Berichte und Backups committet werden, entscheidet Nobu. CSV-, DOCX-, XLSX-Dateien und `index.html` bleiben unberührt (`convert_to_excel.py` liest die DOCX-Dateien, nicht die JSON).
- **`lastModified` nicht ändern.** Das Feld bedeutet „Inhalt des Eintrags wurde geändert“ und wird erst gesetzt, wenn Nobu eine inhaltliche Korrektur freigibt.
- **Nichts behaupten, was nicht belegt ist.** Bei inhaltlichen Abweichungen immer die Quell-URL und die gelesene Stelle nennen; was sich nicht prüfen ließ, als „nicht prüfbar“ führen, nicht als „in Ordnung“.

## Ablauf

### 1. Vorbereitung

- Arbeitsverzeichnis ist das Projektroot (`api_website`).
- `git status --short api_list.json` ausführen. Gibt es uncommittete Änderungen, kurz darauf hinweisen: automatische Korrekturen vermischen sich sonst mit ihnen.
- Heutiges Datum notieren (für Berichtsname und `lastSighted`).

### 2. Links prüfen

```bash
python3 .claude/skills/api-list-check/scripts/check_links.py --out <temp-verzeichnis>/link_results.json
```

Das Skript prüft `url`, `endpoint`, `documentation[].url` und Links in `howToRequestAccess`, in Summe gut 100 URLs, und braucht rund 30 Sekunden bis 1 Minute. Pro Host wartet es 1 Sekunde zwischen Anfragen. Es verändert nichts. Zusätzlich liefert es `data_checks` (fehlende Felder, leeres oder auffälliges `lastSighted`, fehlende Demo-Dateien).

Bedeutung von `kind`:

| kind | Bedeutung | Aktion |
|---|---|---|
| `ok` | erreichbar, keine Weiterleitung | – |
| `redirect_safe` | dauerhafte Weiterleitung (301/308), gleiche Domain, Pfad bleibt erhalten; gilt nur für `url`, `documentation` und Links in `howToRequestAccess` | automatisch korrigieren |
| `redirect_endpoint_cosmetic` | `endpoint` leitet nur kosmetisch um (http→https, www, Schrägstrich) | **nie automatisch**: Die Doku nennt den Endpoint oft genau in der alten Schreibweise (z. B. PLOS: `http://api.plos.org/search`), und Endpoints stehen in fremdem Code. Nur melden, wenn die Doku die neue Schreibweise nennt |
| `redirect_review` | Weiterleitung auf andere Domain, auf die Startseite, nur temporär, oder `endpoint` mit inhaltlicher Änderung | melden, Ziel nennen |
| `endpoint_needs_params` | Endpoint-Basis-URL antwortet 400/404/405 ohne Pfad oder Parameter | in Ordnung, **wenn** die offizielle Dokumentation exakt diese Zeichenfolge als Endpoint nennt (wird in Schritt 3 geprüft); nennt sie einen anderen, als Abweichung melden |
| `blocked` | 401/403/429 (Bot-Schutz oder API-Key-Pflicht) | melden als „manuell prüfen“; nicht als tot werten |
| `dead` | 404/410 | melden; wenn die Dokumentation einen Nachfolger zeigt, diesen nennen |
| `client_error`, `server_error`, `unreachable` | sonstige Fehler, DNS, Timeout | ein zweites Mal von Hand prüfen (WebFetch), bevor es als Problem gemeldet wird; Ausfälle sind oft vorübergehend |
| `template` | URL mit Platzhalter (z. B. `{DOI}`) | übersprungen; im Bericht unter „nicht geprüft“ |

Bei `redirect_review` ist nicht jede Weiterleitung ein Problem: Eine API-Basis-URL, die auf ihre Swagger- oder Startseite weiterleitet (z. B. `api.crossref.org`), ist normal. Melden, wenn sich Domain oder Pfad der **Dokumentation** geändert hat oder das Ziel eine Login- bzw. Cookie-Seite ist.

Ein Skript-Ergebnis ist ein Indiz, kein Urteil: Manche Server sperren Skripte, aber nicht Browser. Bei `blocked`, `dead` und `unreachable` deshalb einmal mit WebFetch und einem einfachen `curl -sS -o /dev/null -w "%{http_code}\n" <url>` (GET, nicht HEAD: manche Server antworten unterschiedlich) gegenprüfen, bevor es in den Bericht kommt. Im ersten Lauf (Oktober 2026) waren Skript-Fehlalarme: ein Timeout bei `wiki.openstreetmap.org`, eine Weiterleitungsschleife bei `api.europeana.eu/console` und ein 429 bei `query.wikidata.org`; alle drei Seiten ließen sich anschließend normal laden.

Manche Hosts sperren Skripte und WebFetch dauerhaft (Cloudflare, Stand Oktober 2026: `europepmc.org`, `viaf.org`, `directory.doabooks.org`, `pro.europeana.eu`, `doaj.org` (Startseite), `data.dnb.de`). Sie lassen sich nur im Browser prüfen. Nicht erneut aufwendig umgehen, sondern im Bericht unter „Links mit Problemen“ als „manuell prüfen“ führen; Seiten, die sich per Browser (Playwright) lesen lassen, nur falls der Inhaltsvergleich sonst gar nicht möglich ist.

### 3. Inhalte prüfen

Für jeden Eintrag die verlinkte Dokumentation lesen und mit dem Eintrag vergleichen. Das ist der aufwendigste Teil (im ersten Lauf rund 10–20 Minuten); deshalb Teil-Agenten (`general-purpose`) im Hintergrund einsetzen: je 4–5 Einträge pro Agent, parallel gestartet. So bleibt der Hauptkontext klein und die Berichte kommen in gleicher Form zurück. Währenddessen können die Problemlinks aus Schritt 2 gegengeprüft werden.

Prompt-Vorlage für jeden Agenten (Einträge, d. h. Namen aus `api_list.json`, einsetzen):

> Prüfe die folgenden Einträge aus `/Users/nobu/api_website/api_list.json`: <Namen>.
> Lies pro Eintrag die Dokumentationsseiten (`documentation[].url`, `url`) mit WebFetch und vergleiche sie mit den Feldern `endpoint`, `limitations`, `license`, `contentFormats`, `description` und `howToRequestAccess` (Registrierung, API-Key, Nutzungsbedingungen).
> Beim `endpoint` gilt: Steht exakt diese Zeichenfolge (Schreibweise inkl. Schrägstrich am Ende) in der offiziellen Dokumentation als Endpoint bzw. Base-URL, ist er in Ordnung, auch wenn er ohne Pfad oder Parameter einen Fehlercode liefert. Nenne ihn nur dann, wenn die Dokumentation einen anderen Endpoint angibt oder keiner belegbar ist.
> Ändere keine Datei. Melde nur Abweichungen, die du an der Quelle belegen kannst. Pro Abweichung: Feld, was im Eintrag steht (Zitat), was die Quelle sagt (Zitat und URL), Sicherheit (`sicher` / `unsicher`), und einen Textvorschlag auf Deutsch und Englisch im Stil des Eintrags.
> Wenn eine Seite nicht lesbar war oder ein Feld sich nicht prüfen ließ, schreibe das ausdrücklich („nicht prüfbar: <Grund>“). Gib am Ende pro Eintrag eine Zeile: `<Name>: keine Abweichung | n Abweichungen | nicht prüfbar`.
> Zahlenangaben (Limits, Größen) besonders genau prüfen; die Einträge nutzen `|` als Trenner zwischen einzelnen Angaben.
> Lege keine Dateien im Projektordner ab. Browser-Werkzeuge (Playwright) nur verwenden, wenn WebFetch und die offizielle OpenAPI-/Swagger-Datei nicht genügen; sie erzeugen sonst Logs im Projekt.

Abweichungen nicht ungeprüft übernehmen: Wenn eine als „sicher“ gemeldete Abweichung im Bericht eine große Rolle spielt (z. B. Lizenz, Kosten, Abschaltung), selbst kurz gegenlesen.

### 4. Änderungen anwenden

Eine Plan-Datei im Temp-Verzeichnis schreiben:

```json
{
  "url_replacements": [{"old": "https://alt.example/doc", "new": "https://neu.example/doc"}],
  "sighted": ["ArXiv", "OpenAlex"]
}
```

- `url_replacements`: alle `redirect_safe`-Fälle aus Schritt 2 (`url` → `proposed_url`). `redirect_endpoint_cosmetic`, `redirect_review` und alles Übrige gehören nicht hinein. Ohne passenden Fall bleibt die Liste leer – das ist ein normales Ergebnis.
- `sighted`: Einträge ohne offenes Problem, d. h. alle Links in Ordnung (oder soeben automatisch korrigiert) und keine inhaltliche Abweichung gefunden. Einträge mit offenen Punkten erhalten das Datum nicht – sie gelten erst als geprüft, wenn Nobu die Punkte geklärt hat.

Vor dem echten Lauf das Backup anlegen (`-n` überschreibt nichts):

```bash
mkdir -p backup && cp -n api_list.json backup/api_list_YYYYMM.json
```

Erst als Trockenlauf, dann echt:

```bash
python3 .claude/skills/api-list-check/scripts/apply_changes.py --plan <plan.json> --dry-run
python3 .claude/skills/api-list-check/scripts/apply_changes.py --plan <plan.json>
git diff --stat api_list.json
```

Das Skript behält das Dateiformat bei, sodass `git diff` nur die tatsächlichen Änderungen zeigt. Erscheinen im Diff viele unerwartete Zeilen, anhalten und nachsehen. Warnt das Skript, dass eine URL nicht gefunden wurde, die Ursache klären, bevor es weitergeht.

### 5. Bericht schreiben

Datei `reports/YYYY-MM.md` (Ordner bei Bedarf anlegen; existiert die Datei schon, `-2` anhängen). Auf Deutsch. Gliederung:

```markdown
# API-Listen-Check YYYY-MM-DD

Zusammenfassung: n Einträge, n URLs geprüft · n automatisch korrigiert · n Punkte zur Entscheidung (davon n sicher, n unsicher) · n nicht prüfbar

Hinweis zur Prüftiefe: Die inhaltlichen Befunde stammen von Teil-Agenten; „sicher“ = Quelle belegt es wörtlich, „unsicher“ = Interpretation nötig. Nenne ausdrücklich, welche Befunde du selbst nachgelesen hast (mindestens die mit großer Tragweite: Abschaltungen, Lizenz, Kosten). Textvorschläge (DE und EN, nur für den betroffenen Teil des Felds) nur bei „sicheren“ Befunden; für „unsichere“ erst nach Entscheidung formulieren, das hält den Bericht lesbar.

## Wichtigste Punkte
Drei bis fünf Punkte nach Tragweite (Abschaltungen, falsche Endpoints oder Lizenzen, veraltete Zahlen, Datenfehler).

## Automatisch korrigiert
- <Eintrag> – <Feld>: `alt` → `neu` (301)

## Zur Entscheidung (Inhalt)
### <Eintrag>
- **<Feld>** (Sicherheit: sicher/unsicher)
  - Aktuell: „…“
  - Quelle: „…“ (<URL>)
  - Vorschlag DE: … / EN: …

## Links mit Problemen
- <Eintrag> – <Feld> – <URL>: <Befund> (<Vorschlag, falls vorhanden>)

## Datenauffälligkeiten
- <Eintrag>: <Befund aus data_checks>

## Nicht geprüft
- <URL / Eintrag>: <Grund>

## Entscheidungsliste (zum Ausfüllen)
Kurze Anleitung: Hinter jedem **Entscheidung:** `ja` (Vorschlag übernehmen), `nein` (nichts ändern) oder eigenen Text eintragen; leere Punkte bleiben unverändert.

### A. Links
- **L1 · <Eintrag> · `<Feld>`** – <Befund>. Vorschlag: <…>.
  **Entscheidung:**

### B. Inhalt (unsicher)
- **E01 · <Eintrag> · `<Feld>`** – <Befund mit Quelle>. Vorschlag: <kurz>.
  **Entscheidung:**

### C. Datenauffälligkeiten
- **D1 · …**
  **Entscheidung:**

### D. Nicht prüfbar (Nobu schaut selbst nach)
- **N1 · <Eintrag>** – <was>:

## Nächste Schritte für Nobu
1. Entscheidungsliste ausfüllen
2. Claude bitten, die Entscheidungsliste einzuarbeiten (Schritt 7)
3. `git diff api_list.json` ansehen, dann committen und pushen, z. B.: `git add api_list.json && git commit -m "Monatlicher API-Check YYYY-MM" && git push`
4. Falls sich URLs oder Inhalte geändert haben: CSV-, DOCX- und XLSX-Dateien werden nicht aus der JSON erzeugt und müssen bei Bedarf von Hand abgeglichen werden.
```

Die Entscheidungsliste bündelt alles, was ein Mensch klären muss: „unsichere“ und „nicht prüfbare“ Befunde, „sichere“ Befunde ohne eindeutigen Vorschlag, Links mit Problemen und Datenauffälligkeiten. Jeder Punkt bekommt eine feste Nummer (L, E, D, N, ggf. K für Kosmetik), damit sich Entscheidungen eindeutig zuordnen lassen. „Sichere“ Befunde mit Textvorschlag stehen nur im Abschnitt „Zur Entscheidung (Inhalt)“, nicht in der Liste, solange Nobu sie nicht gesondert freigibt.

Abschnitte ohne Inhalt mit „–“ füllen statt weglassen, damit man sieht, dass geprüft wurde. Der Ordner `reports/` steht nicht in `.gitignore`, damit sich die Berichte teilen lassen. Weil die Website per GitHub Pages aus dem Repository ausgeliefert wird, sind committete Berichte dort auch abrufbar. Das ist laut Nobu in Ordnung, solange nichts Personenbezogenes oder Vertrauliches im Bericht steht; darauf beim Schreiben achten.

### 6. Abschlussmeldung im Chat

Kurz: Zahlen, Pfad zum Bericht, die zwei oder drei wichtigsten Punkte zur Entscheidung, der Hinweis auf die auszufüllende Entscheidungsliste, und dass noch nichts committet wurde.

### 7. Entscheidungen einarbeiten (eigener Aufruf, nachdem Nobu die Liste ausgefüllt hat)

Auslöser: Nobu bittet darum, die Entscheidungsliste eines Berichts einzuarbeiten.

1. Den Bericht lesen und alle Punkte mit ausgefüllter **Entscheidung:** sammeln. Leere Punkte und `nein` bleiben unverändert. Ist eine Eingabe nicht eindeutig (z. B. „ja“ bei einem Punkt mit mehreren Vorschlägen), nachfragen statt raten.
2. Backup anlegen (siehe Grundsätze und Schritt 4), `cp -n` ohne Überschreiben.
3. Änderungen an `api_list.json` ausführen. Texte bei Bedarf auf Deutsch und Englisch im Stil des Eintrags formulieren und die Formulierungen vor dem Schreiben kurz im Chat zeigen, wenn Nobu keinen eigenen Text vorgegeben hat. Immer nur den betroffenen Teil des Felds ändern. Format der Datei erhalten (2 Leerzeichen, UTF-8, Zeilenumbruch am Ende); danach `python3 -c "import json; json.load(open('api_list.json'))"` und `git diff --stat api_list.json`.
4. Bei jedem geänderten Eintrag `lastModified` auf das heutige Datum setzen. `lastSighted` setzen, wenn der Eintrag nach der Einarbeitung keinen offenen Punkt mehr hat.
5. Im Bericht jeden erledigten Punkt hinter der Entscheidung mit `→ eingearbeitet (YYYY-MM-DD)` markieren, damit der Bericht den Stand zeigt.
6. Nichts committen. Kurz melden, was geändert wurde und was offen bleibt.

## Wenn etwas schiefgeht

- **Skript bricht ab / Netzfehler:** Läuft das Netz überhaupt (eine bekannte URL mit WebFetch testen)? Dann das Skript erneut starten, nicht Teilergebnisse verwenden.
- **Ein Teil-Agent liefert keine verwertbare Antwort:** Nur diese Einträge neu prüfen lassen und im Bericht als „nicht geprüft“ führen, falls es wieder scheitert.
- **Unsicherheit, ob eine Änderung „eindeutig“ ist:** Im Zweifel melden statt korrigieren. Ein übersehener Umzug kostet einen Monat, eine falsche Korrektur kann unbemerkt bleiben.
