# Agents, skills and topics that are not written (step 4)

Read from step 4 of `SKILL.md` when an imported agent, skill, topic or override has a name clash, a risky frontmatter, or differs from what is there.

An agent or skill whose name — file/folder name *or* frontmatter `name`, checked
   case-insensitively, `-high` variants included — matches one this template already ships is
   never written, only reported. Importing it would otherwise start silently overriding that
   template unit; if the human actually wants that, it is a deliberate `docs/ai/local/` override
   done by hand, not an import side effect. An agent with `permissionMode`/`hooks`/`mcpServers` in
   its frontmatter, or a skill with `allowed-tools`/`hooks`, is refused the same way — reported,
   never written, not even with `--yes`; the human adds it by hand if it is genuinely wanted.
   A topic already there with different content is reported as changed and left alone; an
   override whose template topic no longer exists is reported as dead and not written; one whose
   template topic changed since the export is reported as changed-since-export (review by hand).
