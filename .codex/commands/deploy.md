Deploy the current state to the production Docker host.

1. From the project root, run: `docker --context gluesoup-0-docker compose up --build -d`.
2. Wait for the command to complete.
3. Run `docker --context gluesoup-0-docker compose ps` and confirm all services are healthy.
4. Confirm the `cratelynx` Docker network exists; the stack creates it for Traefik to consume as an external network.
5. Tell the user which services were rebuilt and confirm the deploy is done.
