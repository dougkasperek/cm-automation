# Addendum: SSH key type (2026-08-18)

**Pantheon does not support ed25519 keys.** Verified at docs.pantheon.io/ssh-keys:
*"Currently, we do not support `ed25519` keys."* They accept **RSA** and
**ECDSA**, and for ECDSA only the 256-bit size.

This matters because ed25519 is the modern default and is what almost every
guide, and most people's muscle memory, will produce. A rejected key looks like
an authentication failure rather than a key-type failure, so it costs time to
diagnose.

Generate the runner key as:

```bash
ssh-keygen -t rsa -b 4096 -C "cm-automation CI runner" -f ~/.ssh/pantheon_ci -N ""
```

Full walkthrough in `docs/SSH-KEY-SETUP.md`.

Nexcess is a separate question and unverified: it supports SSH keys, but which
types it accepts has not been checked. Do not assume it matches Pantheon.
