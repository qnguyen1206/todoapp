FROM ghcr.io/openclaw/openclaw:latest

ARG CLAWDI_VERSION=0.14.96

USER root
RUN npm install --global --omit=dev "clawdi@${CLAWDI_VERSION}" \
    && clawdi --version

COPY --chown=node:node configure-openclaw.mjs /opt/todoapp/configure-openclaw.mjs

USER node
