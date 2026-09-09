import fs from "node:fs";
import path from "node:path";


const configPath = process.env.OPENCLAW_CONFIG_PATH || "/home/node/.openclaw/openclaw.json";
const enabled = /^(1|true|yes|on)$/i.test(process.env.OPENCLAW_CONFIDENTIAL_AI_ENABLED || "false");


function readConfig() {
  if (!fs.existsSync(configPath)) return {};
  const source = fs.readFileSync(configPath, "utf8").trim();
  if (!source) return {};
  try {
    return JSON.parse(source);
  } catch (error) {
    throw new Error(`Refusing to overwrite invalid OpenClaw config at ${configPath}: ${error.message}`);
  }
}


function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}


function configureGateway(config) {
  const configuredOrigins = (process.env.OPENCLAW_ALLOWED_ORIGINS || "")
    .split(",")
    .map(value => value.trim())
    .filter(Boolean);
  const publicOrigin = (process.env.OPENCLAW_PUBLIC_ORIGIN || "").trim();
  const allowedOrigins = [...new Set([...configuredOrigins, ...(publicOrigin ? [publicOrigin] : [])])];

  config.gateway = asObject(config.gateway);
  config.gateway.mode = (process.env.OPENCLAW_GATEWAY_MODE || "local").trim() || "local";
  config.gateway.controlUi = asObject(config.gateway.controlUi);
  config.gateway.controlUi.allowedOrigins = allowedOrigins;
}


function configureConfidentialProvider(config) {
  if (!enabled) return null;
  if (!(process.env.PHALA_AI_API_KEY || "").trim()) {
    throw new Error("OPENCLAW_CONFIDENTIAL_AI_ENABLED is true, but PHALA_AI_API_KEY is empty");
  }

  const baseUrl = (process.env.OPENCLAW_CONFIDENTIAL_AI_BASE_URL || "https://inference.phala.com/v1")
    .trim()
    .replace(/\/+$/, "");
  const parsedUrl = new URL(baseUrl);
  if (parsedUrl.protocol !== "https:") {
    throw new Error("The confidential inference base URL must use HTTPS");
  }

  const modelId = (process.env.OPENCLAW_CONFIDENTIAL_AI_MODEL || "deepseek/deepseek-v4-flash").trim();
  const alias = (process.env.OPENCLAW_CONFIDENTIAL_AI_ALIAS || "Phala Confidential").trim();
  const timeoutSeconds = Number(process.env.OPENCLAW_CONFIDENTIAL_AI_TIMEOUT_SECONDS || 300);
  if (!modelId) throw new Error("OPENCLAW_CONFIDENTIAL_AI_MODEL cannot be empty");
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) {
    throw new Error("OPENCLAW_CONFIDENTIAL_AI_TIMEOUT_SECONDS must be a positive number");
  }
  const modelRef = `phala/${modelId}`;

  config.models = asObject(config.models);
  config.models.mode = config.models.mode || "merge";
  config.models.providers = asObject(config.models.providers);
  const oldProvider = asObject(config.models.providers.phala);
  const oldModels = Array.isArray(oldProvider.models) ? oldProvider.models : [];
  const oldModel = asObject(oldModels.find(model => model?.id === modelId));
  config.models.providers.phala = {
    ...oldProvider,
    baseUrl,
    apiKey: "${PHALA_AI_API_KEY}",
    api: "openai-completions",
    authHeader: true,
    timeoutSeconds,
    models: [
      ...oldModels.filter(model => model?.id !== modelId),
      {
        ...oldModel,
        id: modelId,
        name: alias,
        input: Array.isArray(oldModel.input) ? oldModel.input : ["text"],
      },
    ],
  };

  config.agents = asObject(config.agents);
  config.agents.defaults = asObject(config.agents.defaults);
  const oldDefaultModel = config.agents.defaults.model;
  config.agents.defaults.model = typeof oldDefaultModel === "string"
    ? { primary: oldDefaultModel }
    : asObject(oldDefaultModel);
  config.agents.defaults.model.primary = modelRef;
  config.agents.defaults.models = asObject(config.agents.defaults.models);
  const oldAgentModel = asObject(config.agents.defaults.models[modelRef]);
  const oldParams = asObject(oldAgentModel.params);
  const oldExtraBody = asObject(oldParams.extra_body || oldParams.extraBody);
  const { extraBody: _legacyExtraBody, extra_body: _oldExtraBody, ...preservedParams } = oldParams;
  config.agents.defaults.models[modelRef] = {
    ...oldAgentModel,
    alias,
    params: {
      ...preservedParams,
      extra_body: {
        ...oldExtraBody,
        provider: {
          ...asObject(oldExtraBody.provider),
          aci_verified: true,
        },
      },
    },
  };
  return modelRef;
}


function writeConfig(config) {
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  const temporaryPath = `${configPath}.tmp-${process.pid}`;
  fs.writeFileSync(temporaryPath, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporaryPath, configPath);
  try {
    fs.chmodSync(configPath, 0o600);
  } catch {
    // Some mounted filesystems do not expose POSIX modes.
  }
}


const config = readConfig();
configureGateway(config);
const modelRef = configureConfidentialProvider(config);
writeConfig(config);
console.log(modelRef
  ? `OpenClaw confidential provider configured: ${modelRef}`
  : "OpenClaw confidential provider disabled; existing model configuration preserved");
