# Datenschutzerklärung

Stand: 17. September 2026

## Verantwortlicher

{{name}}  
{{address}}  
E-Mail: {{email}}

## Bereitstellung und Hosting

BulliExplorer veröffentlicht Reiseberichte sowie Rad-, Wander- und Campinginformationen.
Beim Abruf verarbeitet die Infrastruktur technisch notwendige Verbindungsdaten,
insbesondere IP-Adresse, Zeitpunkt, angefragte Ressource und HTTP-Metadaten.
Ohne diese Angaben können Inhalte nicht ausgeliefert werden.

Hosting und Empfänger: {{hosting}}

Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO. Das berechtigte Interesse liegt
in der sicheren, zuverlässigen Bereitstellung der Website. Eine Verpflichtung,
die Website zu besuchen oder Daten für andere Zwecke bereitzustellen, besteht nicht.

## Betriebs- und Fehlerprotokolle

Die im Projekt verwendete Caddy-Konfiguration aktiviert keine HTTP-Zugriffsprotokolle.
Die Produktionsanwendung deaktiviert auch Uvicorn-Zugriffsprotokolle.
Betriebs- und Fehlerprotokolle können bei Störungen dennoch technische oder
personenbezogene Angaben enthalten. Sie dienen der Sicherheit und Fehlerbehebung,
nicht der Analyse des individuellen Nutzungsverhaltens.

Speicherdauer und Löschung: {{log_retention}}

Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO; berechtigtes Interesse ist die
Sicherheit und Funktionsfähigkeit des Angebots.

## Fehlerüberwachung mit Sentry

Für serverseitige Fehlerberichte wird Sentry (Functional Software, Inc.) eingesetzt.
Das SDK übermittelt Fehlerart, Stacktraces und technische Kontextinformationen.
Performance-Tracing ist deaktiviert. Automatische PII-Erfassung, Stackframe-Lokalvariablen
und Request-Bodies sind deaktiviert. Vor dem Versand werden Benutzerkontext,
zusätzlicher Kontext, Breadcrumbs und Request-Header entfernt; Request-URLs werden
von Zugangsdaten, Query-Parametern und Fragmenten bereinigt. Fehlermeldungen oder
URL-Pfade können trotzdem personenbezogene Angaben enthalten.

Empfänger, Datenregion, Speicherdauer, Auftragsverarbeitung und gegebenenfalls
Drittlandtransfer einschließlich einschlägiger Garantien und Bezugsmöglichkeit:
{{sentry_details}}

Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO; berechtigtes Interesse ist die
Erkennung und Behebung technischer Fehler.
Weitere Informationen: [Sentry Datenschutz](https://sentry.io/privacy/).

## Cloudflare R2

Kartenarchive (PMTiles) und gegebenenfalls Medien werden über Cloudflare R2
bereitgestellt. Bei direktem Abruf erhält Cloudflare insbesondere die IP-Adresse,
die angefragte Ressource und technische HTTP-Metadaten. Das dient der zuverlässigen
Auslieferung der Karten und Medien, auf Grundlage von Art. 6 Abs. 1 lit. f DSGVO.

Konkreter Vertragspartner, Speicherdauer der Request-Daten, Bucket-Jurisdiktion,
Auftragsverarbeitung und gegebenenfalls Drittlandtransfer einschließlich der
anwendbaren Garantien und Bezugsmöglichkeit: {{cloudflare_details}}

Eine EU-Speicherjurisdiktion für Objekte bedeutet nicht automatisch, dass sämtliche
Request-, Support- und Kontodaten ausschließlich in der EU verarbeitet werden.
Weitere Informationen: [Cloudflare Datenschutz](https://www.cloudflare.com/privacypolicy/).

## Karten und geografische Daten

Die Karten verwenden OpenStreetMap-Daten. MapLibre, PMTiles-Bibliotheken und
Schriftarten werden lokal ausgeliefert. Nominatim und Overpass werden durch den
Server bei der Inhaltsverarbeitung abgefragt; normale Seitenaufrufe übertragen
keine Besucher-IP an diese Dienste. Die Kartenarchive werden wie oben beschrieben
bereitgestellt. Kartendaten: © OpenStreetMap-Mitwirkende, ODbL.

## Darstellungspräferenz und Gerätespeicher

Nach ausdrücklicher Auswahl des hellen oder dunklen Modus wird die Auswahl unter
„theme“ im Local Storage gespeichert und beim erneuten Aufruf gelesen. Die
Einstellung bleibt im Browser und wird nicht an uns oder Dritte übermittelt.
Sie bleibt bis zur Änderung oder Löschung der Website-Daten im Browser gespeichert.
Ohne Auswahl wird die Systemeinstellung verwendet und kein neuer Wert gespeichert.
Die Speicherung und der Zugriff dienen der ausdrücklich gewählten Darstellungsfunktion
(§ 25 Abs. 2 Nr. 2 TDDDG).

BulliExplorer setzt auf öffentlichen Leseseiten keine Analyse- oder Marketing-Cookies,
Werbetracker oder browserseitige Sentry-Skripte ein.

## Kontakt per E-Mail

Wenn Sie uns schreiben, verarbeiten wir Ihre E-Mail-Adresse und Nachrichteninhalte
zur Bearbeitung der Anfrage. Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO
(berechtigtes Interesse an der Beantwortung), bei Vertragsanfragen Art. 6 Abs. 1
lit. b DSGVO. Nachrichten werden nach abschließender Bearbeitung gelöscht, sofern
keine gesetzliche Aufbewahrungspflicht oder konkret erforderliche Nachweissicherung besteht.

## Externe Links und veröffentlichte Routen

Externe Links stellen erst nach Anklicken eine Verbindung zum verlinkten Anbieter
her. Dort gilt dessen Datenschutzerklärung. Diese Erklärung bezieht sich auf die
öffentlichen Leseseiten; der Editor ist ein separates Betreiberwerkzeug, das
insbesondere GitHub und gegebenenfalls Cloudflare zur Inhaltsverwaltung verwendet.
Öffentliche Routen stammen aus redaktionell bereitgestellten Inhalten. Auf den
Leseseiten ist kein Upload persönlicher Tracks durch Besucher vorgesehen.

## Ihre Rechte

Sie haben nach den gesetzlichen Voraussetzungen Rechte auf Auskunft (Art. 15 DSGVO),
Berichtigung (Art. 16), Löschung (Art. 17) und Einschränkung (Art. 18). Das Recht
auf Datenübertragbarkeit (Art. 20) gilt insbesondere für automatisierte Verarbeitung
auf Grundlage einer Einwilligung oder eines Vertrags. Eine erteilte Einwilligung
können Sie jederzeit mit Wirkung für die Zukunft widerrufen.

**Bei Verarbeitung aufgrund berechtigter Interessen können Sie aus Gründen, die
sich aus Ihrer besonderen Situation ergeben, jederzeit Widerspruch gemäß Art. 21
Abs. 1 DSGVO einlegen.** Wenden Sie sich dazu an die oben genannte Kontaktadresse.

Sie können sich gemäß Art. 77 DSGVO bei einer Datenschutzaufsichtsbehörde beschweren,
insbesondere am Ort Ihres gewöhnlichen Aufenthalts, Arbeitsplatzes oder des
mutmaßlichen Verstoßes. Für einen Betreiber mit Sitz in Nordrhein-Westfalen:
[Landesbeauftragte für Datenschutz und Informationsfreiheit NRW](https://www.ldi.nrw.de/).

Eine automatisierte Entscheidungsfindung einschließlich Profiling im Sinne von
Art. 22 DSGVO findet nicht statt.
