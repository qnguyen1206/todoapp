# OpenClaw confidential model setup

The custom OpenClaw image runs `configure-openclaw.mjs` before the gateway starts. The configurator safely merges a `phala` provider into the persisted `openclaw.json`, selects it as the default model, and adds this field to every model request:

```json
{"provider": {"aci_verified": true}}
```

The generated configuration stores `${PHALA_AI_API_KEY}` as an environment reference. It never writes the resolved API key into `openclaw.json` or the image.

## Enable it on Phala

1. Create or retrieve a Phala Confidential AI API key.
2. In the CVM Environment Variables panel, set:

   ```text
   PHALA_AI_API_KEY=<your real Phala API key>
   OPENCLAW_CONFIDENTIAL_AI_ENABLED=true
   ```

3. Optionally choose another model from the Phala confidential model catalog:

   ```text
   OPENCLAW_CONFIDENTIAL_AI_MODEL=deepseek/deepseek-v4-flash
   OPENCLAW_CONFIDENTIAL_AI_ALIAS=Phala Confidential
   ```

4. Build and publish the custom OpenClaw image:

   ```powershell
   docker build -t kairu1206/cvm-openclaw:latest ./services/openclaw
   docker push kairu1206/cvm-openclaw:latest
   ```

5. Redeploy the CVM with the updated `docker-compose.yml`. Do not delete `openclaw_data`; it contains the existing OpenClaw configuration and workspace.

## Verify it

In the OpenClaw Control UI, start a new conversation and run `/model status`. The active model should be:

```text
phala/deepseek/deepseek-v4-flash
```

Existing conversations can retain an earlier session-specific model. Run `/model default` in those conversations, or start a new conversation.

If you have SSH access to the CVM, OpenClaw is installed inside its Docker container—not directly on the CVM host. Run its CLI through Docker Compose from the directory containing `docker-compose.yml`:

```sh
docker compose exec openclaw node dist/index.js models list --provider phala
docker compose exec openclaw node dist/index.js models status
docker compose exec openclaw node dist/index.js config validate
```

If SSH opens in a directory that does not contain `docker-compose.yml`, first locate the container:

```sh
docker ps --filter name=openclaw --format '{{.ID}}  {{.Names}}'
```

Then replace `<container-id>` below with the displayed ID:

```sh
docker exec <container-id> node dist/index.js models status
docker exec <container-id> node dist/index.js models list --provider phala
docker exec <container-id> node dist/index.js config validate
```

The OpenClaw container log should contain `OpenClaw confidential provider configured` without printing the API key.

## Disable it

Set `OPENCLAW_CONFIDENTIAL_AI_ENABLED=false` and select another default model in OpenClaw. Disabling the startup merge intentionally does not delete provider settings or conversation history from the persistent volume.
