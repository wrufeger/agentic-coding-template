<?php
declare(strict_types=1);
/*
 * Fassung: 2026-09-17.1   (siehe const FASSUNG unten - bei jeder ausgerollten Aenderung erhoehen)
 *
 * Zweck: Gegenstelle zu .claude/scripts/feedback.py - nimmt die freiwilligen Rueckmeldungen aller Projekte
 *        entgegen, die "Feedback" eingeschaltet haben, legt sie als JSON-Dateien ab und gibt sie gebuendelt
 *        an EINE authentifizierte Anfrage der Template-Seite heraus, die sie danach quittiert und damit
 *        vom Server loescht.
 *
 *        Zwei Operationen, bewusst getrennt (Konzept .templatedev/docs/project/concepts/feedback.md):
 *          - Einliefern ist OEFFENTLICH. Jeder kann POSTen, also wird dem Client nichts geglaubt:
 *            Groessendeckel, Schemapruefung gegen geschlossene Wortlisten, Ratenbegrenzung.
 *          - Abholen ist AUTHENTIFIZIERT (JWT, HS256, gemeinsames Geheimnis). Gelesen wird nur mit Token.
 *
 *        Abholen loescht NICHT sofort: GET /inbox liefert einen Stapel mit ids, POST /ack loescht genau
 *        diese ids. Bricht die Uebertragung dazwischen ab, ist nichts verloren - der naechste GET liefert
 *        denselben Stapel wieder.
 *
 * Aufruf (Deployment):
 *   Diese Datei unter der Zieladresse ablegen, z. B. /var/www/rufeger.de/agentic-coding-feedback/index.php,
 *   sodass https://rufeger.de/agentic-coding-feedback/ darauf zeigt. Die Ablage gehoert AUSSERHALB des
 *   Web-Roots (siehe Konfiguration) - sonst sind die Meldungen per URL abrufbar.
 *
 *   ZWEI DINGE, die am echten Server auftraten (2026-09-15) und die die Clients deshalb selbst abfangen:
 *     - Die Adresse braucht den abschliessenden SCHRAEGSTRICH. Ohne ihn antwortet der Webserver mit 301,
 *       und eine Weiterleitung macht aus einem POST ein GET - die Meldung waere verloren.
 *     - Unterpfade (/inbox, /ack) erreichen das Script nur, wenn der Webserver sie weiterreicht; sonst
 *       liefert er die Startseite der Domain aus. Deshalb ist ?op=inbox der Normalweg, nicht der Ausweg.
 *
 *   Konfiguration per Umgebungsvariable (SetEnv/fastcgi_param) oder per Datei
 *   feedback-endpoint.config.php. Gesucht wird ZUERST eine Ebene UEBER dem Script (ausserhalb des
 *   Web-Roots, dort ist sie per URL nicht erreichbar), danach daneben. Sie gibt ein Array zurueck:
 *     AGENTIC_FEEDBACK_DIR         Ablage, absoluter Pfad ausserhalb des Web-Roots (Pflicht)
 *     AGENTIC_FEEDBACK_JWT_SECRET  gemeinsames Geheimnis, >= 32 Zeichen (Pflicht)
 *     AGENTIC_FEEDBACK_JWT_ISS     erwarteter Aussteller, Default "templatedev"
 *     AGENTIC_FEEDBACK_JWT_AUD     erwartetes Publikum, Default "agentic-coding-feedback"
 *
 * Endpunkte (je auch als ?op=<name> erreichbar, siehe route()):
 *   POST /            Einliefern. Body: JSON nach Schema 1 (gesammelte Meldung) oder Schema 2
 *                     (`art: "direkt"`, von Hand geschrieben - nur `text` ist Pflicht, Projekt-Kennung und
 *                     Kontext duerfen fehlen). Beide brauchen `herkunft`. -> 202 | 400 | 403 | 413 | 429
 *   GET  /inbox       Stapel abholen (JWT). ?max=<1..500> begrenzt. -> 200 | 401
 *   POST /ack         Quittieren und loeschen (JWT). Body: {"ids":["..."]} -> 200 | 400 | 401
 *   GET  /status      Lebenszeichen und Anzahl wartender Meldungen (JWT). -> 200 | 401
 *   GET  /fassung     Fassung, Pruefsumme und Aenderungszeit dieser Datei - oeffentlich, ohne Token.
 *                     Beantwortet "was laeuft hier und ist der Upload angekommen?", ohne dass jemand
 *                     raten muss. -> 200
 *
 * Ausgabeformat: immer JSON, nie HTML - die Meldungen sind Fremdtext und werden nie gerendert.
 */

// ---------------------------------------------------------------- Konfiguration

// Fassung dieser Datei - bei JEDER Aenderung erhoehen, die ausgerollt wird. Sie steht in der Antwort von
// ?op=fassung neben der Pruefsumme, und beide beantworten verschiedene Fragen: Die Pruefsumme BEWEIST, ob
// auf dem Server genau diese Datei liegt (sie kann nicht luegen, weil sie aus dem Inhalt entsteht). Die
// Fassung SAGT einem Menschen, was darin steckt - "2026-09-16.2" ordnet man einem Stand zu, "ce44f3ed38b2"
// niemandem. Eine Pruefsumme ohne Fassung war der Fehler der ersten Runde.
const FASSUNG = '2026-09-17.1';

const SCHEMA = 1;                // gesammelte Meldung des Assistenten
const SCHEMA_DIREKT = 2;         // von Hand geschriebene Nachricht (art: "direkt"), nur `text` ist Pflicht
const DIREKT_MAX = 4000;         // Zeichen je Handnachricht
const BODY_MAX = 32768;          // 32 KB je Meldung
const EINTRAEGE_MAX = 20;        // Eintraege je Meldung
const AUFBEWAHRUNG_TAGE = 730;   // 24 Monate, danach wird beim naechsten Zugriff geloescht
const LIMIT_IP_STUNDE = 30;
const LIMIT_PROJEKT_TAG = 24;
const UHR_TOLERANZ = 60;         // Sekunden Spielraum bei exp/nbf
const KONFIG_SUCHTIEFE = 5;      // wie viele Elternverzeichnisse nach der Konfiguration abgesucht werden

// Herkunftskennung, die jedes Projekt aus dem Template mitfuehrt (siehe HERKUNFT in feedback.py). BEWUSST
// OEFFENTLICH: Sie steht im Template, ist eingecheckt und wird an jedes Projekt vererbt. Sie ist kein
// Zugangsschutz - wer sie faelschen will, liest sie im Repo ab. Sie haelt nur zufaellige Anfragen und
// Scanner-Muell drauusen, also alles, was mit diesem Template nichts zu tun hat. Der Name ist mit Absicht
// nicht "secret"/"token": solche Felder werden unterwegs herausgefiltert.
const HERKUNFT_ERLAUBT = ['agentic-coding-template/1'];

const ARTEN = ['regel', 'script', 'skill', 'ablauf', 'doku', 'fehler', 'mcp', 'link'];
const WEGE = ['neu', 'nachgeruestet'];
const AUSFUELLARTEN = ['leer', 'interview', 'config'];
const SCHALTER = [
    'Orchestrator-Modell', 'Commit-Verhalten', 'Logging', 'Logging-Tiefe', 'Wartung',
    'Wartungsberichte', 'Code-Optimierung', 'Ideen-Ablauf', 'Testtiefe', 'Schreibstil',
];
// Erhebungen nach AI-CONFIG.md § Feedback-Umfang. Jede Gruppe ist eine geschlossene Liste erlaubter
// Schluessel mit ZAHLWERTEN (Ausnahme: die zwei Datumsangaben) - so kann kein Freitext und kein Pfad
// hineinrutschen, egal was ein Absender schickt.
const KENNZAHLEN_INT = ['commits', 'tage_aktiv', 'commits_30_tage', 'commits_docs_ai', 'dateien',
                        'log_zeilen', 'log_sitzungen'];
const KENNZAHLEN_ZAHL = ['groesse_mb'];
const KENNZAHLEN_DATUM = ['erster_commit', 'letzter_commit'];
const REGEL_BEREICHE = ['agents_md', 'claude_md', 'agenten', 'skills', 'scripte', 'checklisten'];
const WERKZEUG_GRUPPEN = ['agenten', 'skills', 'scripte'];

/**
 * Wo die Konfigurationsdatei gesucht wird, in dieser Reihenfolge:
 *   1. Der Pfad aus der Umgebungsvariablen AGENTIC_FEEDBACK_CONFIG (wenn gesetzt, gilt nur dieser).
 *   2. Neben dem Script.
 *   3. Aufwaerts durch die Elternverzeichnisse, bis zu KONFIG_SUCHTIEFE Ebenen.
 *
 * Punkt 3 ist der eigentliche Zweck: Die Datei gehoert OBERHALB des Dokumentwurzelverzeichnisses, denn dort
 * kann keine Anfrage sie erreichen. "Eine Ebene ueber dem Script" genuegt dafuer NICHT - liegt der Endpunkt
 * in einem Unterordner der Hauptseite, ist diese Ebene die Dokumentwurzel selbst und damit sehr wohl
 * abrufbar (genau dieser Irrtum ist am 2026-09-16 aufgefallen). Wie viele Ebenen es bis dorthin sind, weiss
 * nur der Betreiber - deshalb wird gesucht statt geraten.
 *
 * Warum das ueberhaupt zaehlt: Liegt die Datei im Web-Root, bleibt ihr Inhalt nur deshalb geheim, weil PHP
 * sie ausfuehrt und ein `return [...]` nichts ausgibt (der Aufruf liefert eine weisse Seite). Faellt die
 * PHP-Behandlung je aus - Modul deaktiviert, Konfigurationsfehler, eine Umbenennung -, liefert der Server
 * das Geheimnis als Klartext aus. Am sichersten ist deshalb, es gar nicht erst in eine Datei zu schreiben,
 * sondern als Umgebungsvariable zu setzen.
 */
function konfig_kandidaten(): array
{
    $ausUmgebung = getenv('AGENTIC_FEEDBACK_CONFIG');
    if (is_string($ausUmgebung) && $ausUmgebung !== '') {
        return [$ausUmgebung];
    }
    $kandidaten = [];
    $ordner = __DIR__;
    for ($tiefe = 0; $tiefe <= KONFIG_SUCHTIEFE; $tiefe++) {
        $kandidaten[] = $ordner . '/feedback-endpoint.config.php';
        $eltern = dirname($ordner);
        if ($eltern === $ordner) {
            break;  // Dateisystemwurzel erreicht
        }
        $ordner = $eltern;
    }
    return $kandidaten;
}

function konfig(string $schluessel, ?string $default = null): ?string
{
    static $datei = null;
    if ($datei === null) {
        $datei = [];
        foreach (konfig_kandidaten() as $pfad) {
            if (is_readable($pfad)) {
                $datei = (array) require $pfad;
                break;
            }
        }
    }
    $wert = $datei[$schluessel] ?? (getenv($schluessel) ?: null);
    return $wert !== null && $wert !== '' ? (string) $wert : $default;
}

// ---------------------------------------------------------------- Antworten

function antwort(int $code, array $body): never
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), "\n";
    exit;
}

/**
 * Fehlerantwort. Der Grund ist bewusst grob - er sagt dem Absender, was zu tun ist, und einem Angreifer
 * nichts ueber den Zustand des Servers.
 */
function fehler(int $code, string $grund): never
{
    antwort($code, ['ok' => false, 'grund' => $grund]);
}

// ---------------------------------------------------------------- Ablage

function ablage(): string
{
    $dir = konfig('AGENTIC_FEEDBACK_DIR');
    if ($dir === null) {
        error_log('feedback-endpoint: AGENTIC_FEEDBACK_DIR nicht gesetzt');
        fehler(500, 'nicht eingerichtet');
    }
    foreach (['daten', 'limits'] as $unter) {
        $pfad = $dir . '/' . $unter;
        if (!is_dir($pfad) && !@mkdir($pfad, 0700, true) && !is_dir($pfad)) {
            error_log('feedback-endpoint: Ablage nicht anlegbar: ' . $pfad);
            fehler(500, 'nicht eingerichtet');
        }
    }
    return $dir;
}

/** Alle wartenden Meldungen, aelteste zuerst. Beim Durchgehen faellt ab, was die Aufbewahrungsfrist reisst. */
function meldungen(string $dir): array
{
    $grenze = time() - AUFBEWAHRUNG_TAGE * 86400;
    $treffer = glob($dir . '/daten/*/*.json') ?: [];
    $liste = [];
    foreach ($treffer as $pfad) {
        if (filemtime($pfad) < $grenze) {
            @unlink($pfad);
            continue;
        }
        $liste[] = $pfad;
    }
    sort($liste);
    return $liste;
}

/** id -> Pfad. Die id ist der Dateiname ohne Endung und enthaelt nie einen Pfadtrenner (siehe pruefe_id). */
function pfad_zu_id(string $dir, string $id): ?string
{
    $treffer = glob($dir . '/daten/*/' . $id . '.json') ?: [];
    return $treffer[0] ?? null;
}

function pruefe_id(string $id): bool
{
    return (bool) preg_match('/^\d{8}-[0-9a-f]{24}$/', $id);
}

// ---------------------------------------------------------------- Ratenbegrenzung

/**
 * Zaehlt Zugriffe je Schluessel in einem Zeitfenster. Eine Datei je Schluessel, Inhalt eine Liste von
 * Zeitstempeln - genug fuer die erwartete Groessenordnung und ohne Datenbank.
 */
function limit_erreicht(string $dir, string $schluessel, int $max, int $fenster): bool
{
    $pfad = $dir . '/limits/' . sha1($schluessel) . '.json';
    $jetzt = time();
    $fp = @fopen($pfad, 'c+');
    if ($fp === false) {
        return false; // im Zweifel annehmen statt verwerfen - der Deckel schuetzt, er bewacht nicht
    }
    try {
        flock($fp, LOCK_EX);
        $roh = stream_get_contents($fp);
        $stempel = json_decode($roh !== false && $roh !== '' ? $roh : '[]', true);
        $stempel = is_array($stempel) ? array_values(array_filter(
            $stempel,
            static fn ($t): bool => is_int($t) && $t > $jetzt - $fenster
        )) : [];
        if (count($stempel) >= $max) {
            return true;
        }
        $stempel[] = $jetzt;
        ftruncate($fp, 0);
        rewind($fp);
        fwrite($fp, (string) json_encode(array_slice($stempel, -$max)));
        return false;
    } finally {
        flock($fp, LOCK_UN);
        fclose($fp);
    }
}

// ---------------------------------------------------------------- JWT (HS256)

function b64url_dekodieren(string $s): string|false
{
    return base64_decode(strtr($s, '-_', '+/') . str_repeat('=', (4 - strlen($s) % 4) % 4), true);
}

/**
 * Findet das Bearer-Token, egal wie der Webserver es durchreicht.
 *
 * Belegt am 2026-09-16 am echten Endpunkt: Der Authorization-Header kam bei PHP NICHT an - Apache reicht ihn
 * ohne `CGIPassAuth On` bzw. eine passende SetEnvIf-Regel nicht an FastCGI weiter, und der Aufrufer sieht nur
 * ein ratloses "kein Token". Statt die Serverkonfiguration zur Voraussetzung zu machen, werden hier alle
 * ueblichen Wege abgeklappert - zuletzt ein eigener Header, den kein Server anfasst.
 */
function bearer_kopf(): string
{
    foreach (['HTTP_AUTHORIZATION', 'REDIRECT_HTTP_AUTHORIZATION', 'HTTP_X_FEEDBACK_AUTH',
              'REDIRECT_HTTP_X_FEEDBACK_AUTH'] as $name) {
        if (!empty($_SERVER[$name])) {
            return (string) $_SERVER[$name];
        }
    }
    if (function_exists('apache_request_headers')) {
        foreach (apache_request_headers() as $name => $wert) {
            if (strcasecmp($name, 'Authorization') === 0 || strcasecmp($name, 'X-Feedback-Auth') === 0) {
                return (string) $wert;
            }
        }
    }
    return '';
}

/**
 * Prueft das Bearer-Token im Authorization-Header. Nur HS256; "alg": "none" und jedes andere Verfahren
 * werden abgelehnt. Geprueft wird die Signatur zuerst - erst danach wird dem Inhalt des Tokens geglaubt.
 */
function jwt_pruefen(): array
{
    $geheim = konfig('AGENTIC_FEEDBACK_JWT_SECRET');
    if ($geheim === null || strlen($geheim) < 32) {
        error_log('feedback-endpoint: AGENTIC_FEEDBACK_JWT_SECRET fehlt oder ist zu kurz');
        fehler(500, 'nicht eingerichtet');
    }
    $kopf = bearer_kopf();
    if (!preg_match('/^Bearer\s+([A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)$/', $kopf, $m)) {
        fehler(401, 'kein Token');
    }
    [$k, $n, $sig] = explode('.', $m[1]);
    $erwartet = hash_hmac('sha256', $k . '.' . $n, $geheim, true);
    $geliefert = b64url_dekodieren($sig);
    if ($geliefert === false || !hash_equals($erwartet, $geliefert)) {
        fehler(401, 'Signatur ungueltig');
    }
    $kopfdaten = json_decode((string) b64url_dekodieren($k), true);
    $daten = json_decode((string) b64url_dekodieren($n), true);
    if (!is_array($kopfdaten) || !is_array($daten) || ($kopfdaten['alg'] ?? '') !== 'HS256') {
        fehler(401, 'Token unbrauchbar');
    }
    $jetzt = time();
    if (!isset($daten['exp']) || !is_int($daten['exp']) || $daten['exp'] + UHR_TOLERANZ < $jetzt) {
        fehler(401, 'Token abgelaufen');
    }
    if (isset($daten['nbf']) && is_int($daten['nbf']) && $daten['nbf'] - UHR_TOLERANZ > $jetzt) {
        fehler(401, 'Token noch nicht gueltig');
    }
    if (($daten['iss'] ?? '') !== konfig('AGENTIC_FEEDBACK_JWT_ISS', 'templatedev')
        || ($daten['aud'] ?? '') !== konfig('AGENTIC_FEEDBACK_JWT_AUD', 'agentic-coding-feedback')) {
        fehler(401, 'Token nicht fuer diesen Dienst');
    }
    return $daten;
}

// ---------------------------------------------------------------- Einliefern

function body_lesen(): array
{
    if ((int) ($_SERVER['CONTENT_LENGTH'] ?? 0) > BODY_MAX) {
        fehler(413, 'zu gross');
    }
    $roh = file_get_contents('php://input', false, null, 0, BODY_MAX + 1);
    if ($roh === false || strlen($roh) > BODY_MAX) {
        fehler(413, 'zu gross');
    }
    $daten = json_decode($roh, true);
    if (!is_array($daten)) {
        fehler(400, 'kein JSON-Objekt');
    }
    return $daten;
}

function text(mixed $wert, int $max): ?string
{
    if (!is_string($wert) || !mb_check_encoding($wert, 'UTF-8')) {
        return null;
    }
    $wert = trim((string) preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $wert));
    if ($wert === '' || mb_strlen($wert) > $max) {
        return null;
    }
    return $wert;
}

function wortliste(mixed $wert, int $max_eintraege): array
{
    if (!is_array($wert)) {
        return [];
    }
    $raus = [];
    foreach (array_slice($wert, 0, $max_eintraege) as $e) {
        if (is_string($e) && preg_match('/^[A-Za-z0-9 ._+-]{1,40}$/', $e)) {
            $raus[] = $e;
        }
    }
    return $raus;
}

/**
 * Baut aus dem Body eine neue, saubere Nutzlast - Feld fuer Feld, nur Bekanntes. Unbekannte Felder fallen
 * weg, statt gespeichert zu werden: Was hier nicht abgeschrieben wird, liegt auch nie auf der Platte.
 */
/**
 * Von Hand geschriebene Nachricht (Schema 2, `art: "direkt"`). Pflicht ist nur der Text; Projekt-Kennung und
 * Kontext fehlen absichtlich, wenn im Projekt "Feedback: aus" steht - dieser Kanal ist auch dann offen, weil
 * ihn ein Mensch selbst ausloest und selbst formuliert.
 */
function validieren_direkt(array $b): array
{
    $text = text($b['text'] ?? null, DIREKT_MAX);
    if ($text === null) {
        fehler(400, 'text fehlt oder ist zu lang');
    }
    $nutzlast = [
        'schema' => SCHEMA_DIREKT,
        'herkunft' => (string) $b['herkunft'],
        'art' => 'direkt',
        'datum' => is_string($b['datum'] ?? null) && preg_match('/^\d{4}-\d{2}-\d{2}$/', $b['datum'])
            ? $b['datum'] : gmdate('Y-m-d'),
        'text' => $text,
    ];
    // Kontext ist optional - jedes Feld einzeln geprueft, nichts durchgereicht.
    $id = $b['projekt_id'] ?? null;
    if (is_string($id) && preg_match('/^[0-9a-f]{32}$/', $id)) {
        $nutzlast['projekt_id'] = $id;
    }
    if (is_string($b['template_basis'] ?? null) && preg_match('/^[0-9a-f]{7,40}$/', $b['template_basis'])) {
        $nutzlast['template_basis'] = $b['template_basis'];
    }
    if (in_array($b['weg'] ?? '', WEGE, true)) {
        $nutzlast['weg'] = $b['weg'];
    }
    if (in_array($b['ausfuellart'] ?? '', AUSFUELLARTEN, true)) {
        $nutzlast['ausfuellart'] = $b['ausfuellart'];
    }
    return $nutzlast;
}

function validieren(array $b): array
{
    // Erste Huerde, vor allem anderen: Kommt das ueberhaupt aus einem Projekt mit diesem Template?
    if (!in_array($b['herkunft'] ?? null, HERKUNFT_ERLAUBT, true)) {
        fehler(403, 'unbekannte Herkunft');
    }
    if (($b['schema'] ?? null) === SCHEMA_DIREKT || ($b['art'] ?? null) === 'direkt') {
        return validieren_direkt($b);
    }
    if (($b['schema'] ?? null) !== SCHEMA) {
        fehler(400, 'unbekanntes Schema');
    }
    $id = $b['projekt_id'] ?? '';
    if (!is_string($id) || !preg_match('/^[0-9a-f]{32}$/', $id)) {
        fehler(400, 'projekt_id fehlt oder ist unbrauchbar');
    }
    $datum = is_string($b['datum'] ?? null) && preg_match('/^\d{4}-\d{2}-\d{2}$/', $b['datum'])
        ? $b['datum'] : gmdate('Y-m-d');
    $basis = is_string($b['template_basis'] ?? null) && preg_match('/^[0-9a-f]{7,40}$/', $b['template_basis'])
        ? $b['template_basis'] : null;

    $schalter = [];
    if (is_array($b['schalter'] ?? null)) {
        foreach (SCHALTER as $k) {
            $w = text($b['schalter'][$k] ?? null, 40);
            if ($w !== null) {
                $schalter[$k] = $w;
            }
        }
    }

    $mcp = [];
    if (is_array($b['mcp_server'] ?? null)) {
        $aus_katalog = wortliste($b['mcp_server']['aus_katalog'] ?? null, 30);
        if ($aus_katalog !== []) {
            $mcp['aus_katalog'] = $aus_katalog;
        }
        if (isset($b['mcp_server']['andere']) && is_int($b['mcp_server']['andere'])) {
            $mcp['andere'] = max(0, min(99, $b['mcp_server']['andere']));
        }
    }

    $eintraege = [];
    if (is_array($b['eintraege'] ?? null)) {
        foreach (array_slice($b['eintraege'], 0, EINTRAEGE_MAX) as $e) {
            if (!is_array($e) || !in_array($e['art'] ?? '', ARTEN, true)) {
                continue;
            }
            $titel = text($e['titel'] ?? null, 200);
            $inhalt = text($e['text'] ?? null, 2000);
            if ($titel === null || $inhalt === null) {
                continue;
            }
            $neu = ['art' => $e['art'], 'titel' => $titel, 'text' => $inhalt];
            if (is_string($e['datum'] ?? null) && preg_match('/^\d{4}-\d{2}-\d{2}$/', $e['datum'])) {
                $neu['datum'] = $e['datum'];
            }
            $url = text($e['url'] ?? null, 300);
            if ($url !== null && preg_match('#^https?://[^\s<>"\']+$#', $url)) {
                $neu['url'] = $url;
            }
            $eintraege[] = $neu;
        }
    }

    $kennzahlen = [];
    if (is_array($b['kennzahlen'] ?? null)) {
        foreach (KENNZAHLEN_INT as $k) {
            if (isset($b['kennzahlen'][$k]) && is_int($b['kennzahlen'][$k])) {
                $kennzahlen[$k] = max(0, min(10_000_000, $b['kennzahlen'][$k]));
            }
        }
        foreach (KENNZAHLEN_ZAHL as $k) {
            if (isset($b['kennzahlen'][$k]) && is_numeric($b['kennzahlen'][$k])) {
                $kennzahlen[$k] = round(max(0, min(1_000_000, (float) $b['kennzahlen'][$k])), 1);
            }
        }
        foreach (KENNZAHLEN_DATUM as $k) {
            if (is_string($b['kennzahlen'][$k] ?? null)
                && preg_match('/^\d{4}-\d{2}-\d{2}$/', $b['kennzahlen'][$k])) {
                $kennzahlen[$k] = $b['kennzahlen'][$k];
            }
        }
    }

    $zaehler = static function (mixed $roh, array $erlaubt): array {
        $raus = [];
        if (is_array($roh)) {
            foreach ($erlaubt as $k) {
                if (isset($roh[$k]) && is_int($roh[$k])) {
                    $raus[$k] = max(0, min(100000, $roh[$k]));
                }
            }
        }
        return $raus;
    };

    $nutzlast = [
        'schema' => SCHEMA,
        'herkunft' => (string) $b['herkunft'],
        'projekt_id' => $id,
        'datum' => $datum,
        'template_basis' => $basis,
        'weg' => in_array($b['weg'] ?? '', WEGE, true) ? $b['weg'] : null,
        'ausfuellart' => in_array($b['ausfuellart'] ?? '', AUSFUELLARTEN, true) ? $b['ausfuellart'] : null,
        'werkzeuge_entfernt' => wortliste($b['werkzeuge_entfernt'] ?? null, 20),
        'regelsaetze' => wortliste($b['regelsaetze'] ?? null, 20),
        'eintraege' => $eintraege,
    ];
    // Nur aufnehmen, was tatsaechlich erhoben wurde - leere Gruppen sind Rauschen in der Auswertung. Und
    // sie waeren nicht bloss leer, sondern falsch geformt: PHP macht aus einem leeren Array in JSON `[]`,
    // nicht `{}`. Wer die Meldung spaeter auswertet, bekaeme also mal eine Liste, mal ein Objekt.
    foreach ([['schalter', $schalter],
              ['mcp_server', $mcp],
              ['kennzahlen', $kennzahlen],
              ['regel_aenderungen', $zaehler($b['regel_aenderungen'] ?? null, REGEL_BEREICHE)],
              ['werkzeuge', $zaehler($b['werkzeuge'] ?? null, WERKZEUG_GRUPPEN)]] as [$name, $wert]) {
        if ($wert !== []) {
            $nutzlast[$name] = $wert;
        }
    }
    if (is_string($b['umfang'] ?? null) && preg_match('/^[abc](,[abc])*$/', $b['umfang'])) {
        $nutzlast['umfang'] = $b['umfang'];
    }
    // Vom Menschen selbst geschriebene Antworten (feedback.md). Frage und Antwort einzeln geprueft und
    // gekuerzt - mehr als 10 Abschnitte hat der Fragebogen nicht.
    if (is_array($b['fragebogen'] ?? null)) {
        $fragebogen = [];
        foreach (array_slice($b['fragebogen'], 0, 10) as $e) {
            $frage = is_array($e) ? text($e['frage'] ?? null, 200) : null;
            $antwort = is_array($e) ? text($e['antwort'] ?? null, 2000) : null;
            if ($frage !== null && $antwort !== null) {
                $fragebogen[] = ['frage' => $frage, 'antwort' => $antwort];
            }
        }
        if ($fragebogen !== []) {
            $nutzlast['fragebogen'] = $fragebogen;
        }
    }
    $repo = text($b['repo_url'] ?? null, 300);
    if ($repo !== null && preg_match('#^https://[^\s<>"\']+$#', $repo)) {
        $nutzlast['repo_url'] = $repo;
    }
    return $nutzlast;
}

function einliefern(): never
{
    $dir = ablage();
    $ip = (string) ($_SERVER['REMOTE_ADDR'] ?? '-');
    if (limit_erreicht($dir, 'ip:' . $ip, LIMIT_IP_STUNDE, 3600)) {
        fehler(429, 'zu viele Meldungen von dieser Adresse');
    }
    $nutzlast = validieren(body_lesen());
    // Eine Handnachricht ohne Projekt-Kennung (Feedback: aus) laesst sich nur ueber die IP begrenzen - genau
    // das ist der Preis dafuer, dass sie nichts ueber ihr Projekt verraet.
    if (isset($nutzlast['projekt_id'])
        && limit_erreicht($dir, 'projekt:' . $nutzlast['projekt_id'], LIMIT_PROJEKT_TAG, 86400)) {
        fehler(429, 'zu viele Meldungen dieses Projekts');
    }
    $ordner = $dir . '/daten/' . gmdate('Y-m');
    if (!is_dir($ordner) && !@mkdir($ordner, 0700, true) && !is_dir($ordner)) {
        error_log('feedback-endpoint: Monatsordner nicht anlegbar: ' . $ordner);
        fehler(500, 'Ablage nicht schreibbar');
    }
    $id = gmdate('Ymd') . '-' . bin2hex(random_bytes(12));
    $satz = ['id' => $id, 'empfangen' => gmdate('c'), 'nutzlast' => $nutzlast];
    $tmp = $ordner . '/.' . $id . '.tmp';
    $ziel = $ordner . '/' . $id . '.json';
    $json = json_encode($satz, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($json === false || @file_put_contents($tmp, $json . "\n") === false || !@rename($tmp, $ziel)) {
        @unlink($tmp);
        error_log('feedback-endpoint: Schreiben fehlgeschlagen: ' . $ziel);
        fehler(500, 'Ablage nicht schreibbar');
    }
    @chmod($ziel, 0600);
    antwort(202, ['ok' => true, 'id' => $id]);
}

// ---------------------------------------------------------------- Abholen und Quittieren

function inbox(): never
{
    jwt_pruefen();
    $dir = ablage();
    $max = max(1, min(500, (int) ($_GET['max'] ?? 100)));
    $alle = meldungen($dir);
    $stapel = [];
    foreach (array_slice($alle, 0, $max) as $pfad) {
        $satz = json_decode((string) file_get_contents($pfad), true);
        if (is_array($satz)) {
            $stapel[] = $satz;
        }
    }
    antwort(200, [
        'ok' => true,
        'stapel' => $stapel,
        'geliefert' => count($stapel),
        'wartend_gesamt' => count($alle),
        'hinweis' => 'Geloescht wird erst durch POST /ack mit diesen ids.',
    ]);
}

function ack(): never
{
    jwt_pruefen();
    $dir = ablage();
    $ids = body_lesen()['ids'] ?? null;
    if (!is_array($ids) || $ids === []) {
        fehler(400, 'ids fehlen');
    }
    $geloescht = 0;
    $unbekannt = [];
    foreach (array_slice($ids, 0, 500) as $id) {
        if (!is_string($id) || !pruefe_id($id)) {
            $unbekannt[] = is_string($id) ? substr($id, 0, 40) : '(kein Text)';
            continue;
        }
        $pfad = pfad_zu_id($dir, $id);
        if ($pfad !== null && @unlink($pfad)) {
            $geloescht++;
        } else {
            $unbekannt[] = $id;
        }
    }
    antwort(200, [
        'ok' => true,
        'geloescht' => $geloescht,
        'unbekannt' => $unbekannt,
        'wartend_gesamt' => count(meldungen($dir)),
    ]);
}

/**
 * Welche Fassung laeuft hier? Oeffentlich und ohne Token - die Antwort verraet nichts, was nicht ohnehin
 * im Repo steht, und beantwortet die Frage, die sonst jedes Mal zu Rateversuchen fuehrt: "Ist der Upload
 * angekommen?" Statt einer gepflegten Versionsnummer (die man zu erhoehen vergisst) die Pruefsumme der
 * Datei selbst. Zeilenenden werden vorher vereinheitlicht, sonst meldet ein Upload per FTP im Textmodus
 * einen Unterschied, den es inhaltlich nicht gibt.
 */
function fassung(): never
{
    $roh = @file_get_contents(__FILE__);
    antwort(200, [
        'ok' => true,
        'fassung' => FASSUNG,
        'datei' => $roh === false ? null : substr(sha1(str_replace("\r\n", "\n", $roh)), 0, 12),
        'geaendert' => @filemtime(__FILE__) ? gmdate('c', filemtime(__FILE__)) : null,
        'zeit' => gmdate('c'),
    ]);
}

function status(): never
{
    jwt_pruefen();
    antwort(200, [
        'ok' => true,
        'wartend_gesamt' => count(meldungen(ablage())),
        'aufbewahrung_tage' => AUFBEWAHRUNG_TAGE,
        'zeit' => gmdate('c'),
    ]);
}

// ---------------------------------------------------------------- Routing

/**
 * Ermittelt den Endpunkt aus der Anfrage. PATH_INFO ist der Normalfall; fehlt es (manche FPM-Konfigurationen,
 * der eingebaute PHP-Server im Router-Modus), wird es aus REQUEST_URI abzueglich des Script-Pfads gebildet.
 * ?op=inbox bleibt als letzter Ausweg fuer Umgebungen ohne Pfadinformation.
 */
function route(): string
{
    $pfad = (string) ($_SERVER['PATH_INFO'] ?? '');
    if ($pfad === '') {
        $uri = (string) (parse_url((string) ($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH) ?: '');
        $script = (string) ($_SERVER['SCRIPT_NAME'] ?? '');
        $basis = rtrim(dirname($script), '/\\');
        if ($script !== '' && str_starts_with($uri, $script)) {
            $pfad = substr($uri, strlen($script));
        } elseif ($basis !== '' && $basis !== '.' && str_starts_with($uri, $basis)) {
            $pfad = substr($uri, strlen($basis));
        } else {
            $pfad = $uri;
        }
    }
    if (trim($pfad, '/') === '') {
        $pfad = (string) ($_GET['op'] ?? '');
    }
    return trim($pfad, '/');
}

$methode = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$route = route();

if ($methode === 'OPTIONS') {
    header('Allow: GET, POST');
    antwort(204, []);
}

match (true) {
    $route === '' && $methode === 'POST' => einliefern(),
    $route === 'inbox' && $methode === 'GET' => inbox(),
    $route === 'ack' && $methode === 'POST' => ack(),
    $route === 'status' && $methode === 'GET' => status(),
    $route === 'fassung' && $methode === 'GET' => fassung(),
    in_array($route, ['', 'inbox', 'ack', 'status', 'fassung'], true) => fehler(405, 'Methode passt nicht zum Endpunkt'),
    default => fehler(404, 'unbekannter Endpunkt'),
};
