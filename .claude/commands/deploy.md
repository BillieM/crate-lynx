Deploy the current state to the production Docker host.

1. From the project root, run: `docker-compose up --build -d`
2. Wait for the command to complete.
3. Tell the user which services were rebuilt and confirm the deploy is done.

Note: use `docker-compose` (not `docker compose`) — the Compose plugin is not installed on the remote host. The active Docker context is `gluesoup-1` (the production server); do not switch contexts.
