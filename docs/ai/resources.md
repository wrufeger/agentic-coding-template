> Datenstand: 2026-09-13 – Status: aktuell — vom Template gepflegt

# Agentic Coding — Quellen und Einstieg

Sammlung geprüfter Quellen rund um die Zusammenarbeit mit KI-Assistenten in der Softwareentwicklung: was der
Ansatz ist, wie man einsteigt, welche Werkzeuge es gibt, wo man Neues erfährt und was die bekannten Grenzen
sind. Gedacht für alle, die in diesem Projekt mitarbeiten und den Hintergrund brauchen.

**Diese Datei pflegt das Template**, nicht das Projekt. `/update-template` zieht die jeweils aktuelle Fassung
nach (`docs/ai/checklists.md` § „Template-Update"). Eigene Fundstellen deshalb unten unter „Eigene Quellen
dieses Projekts" ergänzen — dieser Abschnitt bleibt beim Aktualisieren unberührt. Alle Links wurden am
2026-09-13 abgerufen.

## Was ist Agentic Coding

- [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) — Grundlagentext
  zu Workflow- und Agenten-Mustern, Bezugspunkt vieler späterer Leitfäden.
- [What is agentic coding?](https://cloud.google.com/discover/what-is-agentic-coding) — Einordnung von Google
  Cloud, klare Abgrenzung zur Code-Vervollständigung.
- [Agentic Engineering Patterns](https://simonwillison.net/2026/Feb/23/agentic-engineering-patterns/) —
  laufend gepflegter Musterkatalog eines unabhängigen Fachautors.
- [Zwischen Tempo und Nachhaltigkeit](https://www.heise.de/en/background/Between-Speed-and-Sustainability-AI-Agents-in-Software-Development-11098799.html)
  — deutschsprachiger Hintergrund, der die Zielkonflikte ernst nimmt.

## Einstieg und Tutorials

- [Claude Code Quickstart](https://code.claude.com/docs/en/quickstart) — Einstieg Schritt für Schritt.
- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices) — Kontextverwaltung, Planen,
  Review-Schritt; vieles davon steckt auch in `AGENTS.md`.
- [GitHub Copilot — Best practices](https://docs.github.com/en/copilot/get-started/best-practices) — offizielle
  Praxisempfehlungen.
- [Cursor Quickstart](https://cursor.com/docs/get-started/quickstart) — Einstieg des Herstellers.
- [Aider — Usage](https://aider.chat/docs/usage.html) — knapper, werkzeugnaher Praxisleitfaden.
- [KI-Chat: Agentic Coding (Uni Mainz)](https://www.zdv.uni-mainz.de/ki-chat-agentic-coding/) —
  **deutschsprachig**, praxisnahe Anleitung einer Hochschule.

## Werkzeuge und ihre Dokumentation

Wie die einzelnen Werkzeuge parallele Worker starten, steht in `AGENTS.md` § „Worker starten".

- [Claude Code](https://code.claude.com/docs/en/overview)
- [GitHub Copilot](https://docs.github.com/en/copilot)
- [Cursor](https://cursor.com/docs)
- [Aider](https://aider.chat/docs/)
- [Gemini CLI](https://google-gemini.github.io/gemini-cli/docs/)
- [OpenAI Codex](https://developers.openai.com/codex)
- [Cline](https://docs.cline.bot/)
- [OpenHands](https://docs.all-hands.dev/)
- [Amp](https://ampcode.com/manual)
- [Devin](https://docs.devin.ai/)
- Roo Code wurde am 15.05.2026 eingestellt; ältere Anleitungen nennen es noch. Das Projekt selbst verweist auf
  Cline als Nachfolger.

## Anbieter und Modelle

- [Anthropic](https://www.anthropic.com/) · [OpenAI](https://openai.com/) ·
  [Google AI for Developers](https://ai.google.dev/) · [Meta AI](https://ai.meta.com/) ·
  [Mistral AI](https://mistral.ai/) · [xAI](https://docs.x.ai/) · [DeepSeek](https://www.deepseek.com/) ·
  [Qwen](https://github.com/QwenLM)
- Lokal betreiben: [Ollama](https://docs.ollama.com/) · [LM Studio](https://lmstudio.ai/docs/app) ·
  [llama.cpp](https://github.com/ggml-org/llama.cpp) · [vLLM](https://docs.vllm.ai/)

## Standards und Konventionen

- [Model Context Protocol](https://modelcontextprotocol.io/) — Anbindung von Werkzeugen und Datenquellen an
  Assistenten; in diesem Projekt über `.mcp.json`.
- [AGENTS.md](https://agents.md/) — herstellerübergreifende Konvention für Regeldateien, die dieses Template
  aufgreift. [Spezifikation und Historie](https://github.com/agentsmd/agents.md).

## News und laufende Quellen

Die Changelogs veralten schnell — genau deshalb stehen sie hier.

- [Claude Code Changelog](https://code.claude.com/docs/en/changelog)
- [GitHub Changelog zu Copilot](https://github.blog/changelog/label/copilot/)
- [Cursor Changelog](https://cursor.com/changelog)
- [Codex CLI Doku](https://learn.chatgpt.com/docs/codex/cli)
- [Aider Release History](https://aider.chat/HISTORY.html)
- [Latent Space](https://www.latent.space/) — Newsletter und Podcast mit Einordnung statt Ankündigungen.
- [Hacker News](https://news.ycombinator.com/) — Diskussion und Filter für Werkzeug-Neuigkeiten.

## Kritik und Grenzen

Dieser Abschnitt gehört dazu. Wer die Grenzen kennt, delegiert besser.

- [METR: Produktivität erfahrener Entwickler](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)
  — randomisierte Studie: die Teilnehmer waren mit Assistenz langsamer, hielten sich aber für schneller.
- [GitClear: The Maintainability Gap](https://www.gitclear.com/the_ai_code_quality_maintainability_gap) —
  Auswertung sehr vieler Codeänderungen zu Duplikaten und rückläufigem Refactoring.
- [OWASP: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) — Referenz zum
  wichtigsten Angriffsweg samt Gegenmaßnahmen.
- [Your AI, My Shell (arXiv)](https://arxiv.org/pdf/2509.22040) — Sicherheitsforschung zu Angriffen auf
  Coding-Agenten selbst.

Was daraus für dieses Projekt folgt, steht in `AGENTS.md` § „Umgang mit Sicherheits-/Safeguard-Warnungen" und
§ „Zugriff auf laufende Systeme".

## Eigene Quellen dieses Projekts

*(hier eigene Fundstellen ergänzen — bleibt bei `/update-template` unberührt)*

> **Links aus diesem Abschnitt werden mitgeteilt**, wenn die freiwillige Rückmeldung eingeschaltet ist
> (`AI-CONFIG.md` § `Feedback`, standardmäßig **aus**). Gesendet werden nur Adresse, Titel und ein Satz,
> warum der Link nützlich ist — nichts sonst. Interne Adressen lehnt die Prüfung ohnehin ab: localhost,
> private IP-Bereiche, `*.intern`, `*.local` und alles mit Zugangsdaten in der URL.
> **Was hier nicht landen soll, gehört nach „Private Links" ganz unten.**

## Private Links

*(bleibt immer im Projekt — von hier wird **nie** etwas gesendet, auch bei eingeschalteter Rückmeldung nicht)*

Für alles, was nur hier nützlich ist oder niemanden etwas angeht: internes Wiki, Ticketsystem, Zugänge,
Kundendokumentation, Notizen. Der Assistent liest diesen Abschnitt wie jeden anderen — er nimmt daraus nur
nichts in eine Rückmeldung auf.
