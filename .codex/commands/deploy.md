Deploy the current state to the production Docker host.

1. From the project root, run: `docker compose up --build -d` if the local Docker CLI has the Compose plugin; otherwise run `docker-compose up --build -d`.
2. Wait for the command to complete.
3. Run `docker compose ps` or `docker-compose ps` and confirm all services are healthy.
4. Confirm the `cratelynx` Docker network exists; the stack creates it for Traefik to consume as an external network.
5. Tell the user which services were rebuilt and confirm the deploy is done.

Note: the active Docker context must be `gluesoup-0-docker-1` (the production server). Docker contexts use the Compose client on the local machine, so use whichever Compose command is installed locally.
