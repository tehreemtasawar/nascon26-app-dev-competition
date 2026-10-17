# Backend tests

`run_tests.sh` is the portable smoke runner used by the repository. It verifies
health, reset, custom sport registration, and round-robin generation. The
server also has targeted runtime checks for signed scoring, standings,
idempotent checkout, authentication, and RBAC probes.
