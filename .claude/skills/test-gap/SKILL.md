---
name: test-gap
description: Testlücken in einem Bereich finden, nach Risiko priorisieren und nach Freigabe schließen - Bestand messen, Liste vorlegen, gezielt Tests schreiben statt Coverage-Prozente zu jagen. Auslöser - "/test-gap", "Testlücken finden", "sind wir hier getestet?", "Tests für X nachziehen".
---

# Testlücken finden und schließen

Findet Bereiche ohne (ausreichende) Testabdeckung, legt sie priorisiert vor und schließt sie nach Freigabe
durch {{AUFTRAGGEBER}} oder den aufrufenden Auftrag. Der Skill ist **nicht** dafür da, eine Coverage-Prozentzahl
zu erhöhen — die Zahl ist ein Anhaltspunkt, kein Ziel.

## Ablauf

1. **Bestand messen.** Welche Bereiche haben Tests, welche nicht (`docs/project/testing.md`, Coverage-Report
   falls vorhanden). Coverage dient nur zum Auffinden weißer Flecken, nicht als Erfolgsmaß.
2. **Nach Risiko priorisieren, nicht nach Prozentzahl.** Zuerst Bereiche mit Geldbezug, Auth/Rechten,
   Datenverlust-Potenzial, dann häufig geänderter Code (`git log` auf Änderungshäufigkeit), erst danach
   selten berührter Code. Trivialer Code (Getter, Konstanten, reine Weiterleitung) fällt ganz heraus.
3. **Lücken als Liste vorlegen.** Bereich, Risiko, Begründung — kurz, vor dem Schreiben irgendeines Tests.
   Bei einem eigenständigen `/test-gap`-Auftrag: Freigabe von {{AUFTRAGGEBER}} einholen, welche Lücken
   geschlossen werden. Läuft der Skill als Vorbedingung innerhalb von `/refactor`, genügt die Freigabe durch
   den aufrufenden Auftrag für den betroffenen Bereich.
4. **Tests schreiben, je Test ein Verhalten.** Sprechender Name, der das erwartete Verhalten beschreibt, nicht
   die Implementierung. Ein Test prüft, was der Code tun soll — nicht nur, was er zufällig gerade tut.
5. **Pflichtläufe.** Neue Tests laufen zusammen mit der bestehenden Suite grün (`AI-CONFIG.md` § Technik).
6. Beleg sichern (Testlauf grün, Liste der geschlossenen Lücken), dann Checkliste
   „Aufgabe abschließen" (`/commit`).

## Grenzen

- **Coverage-Prozente sind kein Ziel** und werden nicht als Erfolg gemeldet. Gemeldet wird, welches Risiko
  jetzt abgedeckt ist.
- **Kein Test für trivialen Code** (Getter, Konstanten, reine Durchreichung) — das verwässert nur die Suite.
- **Ein Test, der nur die Implementierung bestätigt**, statt das gewünschte Verhalten zu prüfen, ist wertlos
  und wird nicht geschrieben, auch wenn er die Zeile grün macht.
- Ohne Freigabe der priorisierten Liste wird nicht mit dem Schreiben begonnen (Ausnahme: als Vorbedingung
  innerhalb eines anderen Skills, siehe Schritt 3).
