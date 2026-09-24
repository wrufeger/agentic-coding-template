<!-- act:default -->
One file per entry (`YYYY-MM-DD-<slug>.md`) — things waiting for a decision, versioned and
visible instead of sent privately. Both the user and the assistant add entries; nothing is
deleted, only answered and archived.

Each file opens with two header fields:

```text
for: all            # or a workspace identity - who it is addressed to
status: open        # open -> answered -> done
```

`open` waits on a person. `answered` means a person replied but nobody has worked the answer
into its place yet — that is the number the session start reports. `done` is finished and
can be moved to `docs/ai/work/archive/`.
