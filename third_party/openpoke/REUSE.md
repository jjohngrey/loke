# OpenPoke attribution

Source: https://github.com/shlokkhemani/openpoke
Pinned snapshot: 5b5f635935a64ab37884c025d70abb0ed731c094
License: MIT, retained in LICENSE.

Adapted files:
- server/openrouter_client/client.py → layers/intelligence/loke_intelligence/openrouter.py
- server/services/trigger_scheduler.py lifecycle → layers/intelligence/loke_intelligence/scheduler.py
- web/app/api/chat/route.ts HTTP proxy → layers/input/web/app/api/backend/[...path]/route.ts

The learning contracts, deterministic policy, storage and desktop UI are Loke-specific.
Gmail/Composio and unrestricted agent execution loops were not copied.
