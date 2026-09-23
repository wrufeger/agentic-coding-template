# -*- coding: utf-8 -*-
#
# Purpose: Check modules for .act/hooks/dispatch.py — one file per hook check, plus the small
#          helper modules the checks share (common.py, shell_targets.py). dispatch.py stays the
#          single entry point: it reads the hook payload and runs the checks registered in its
#          own PreToolUse/SessionStart lists, in order. See dispatch.py's header comment for the
#          convention a new check follows.
#
# This package is imported only from dispatch.py (and, directly, by a probe that reaches into
# dispatch's internals for a white-box test — see dispatch.py's own docstring on backward
# compatibility). Nothing here assumes dispatch.py's sys.path setup beyond what dispatch.py has
# already done by the time it imports this package.
