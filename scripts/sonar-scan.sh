#!/usr/bin/env bash
set -euo pipefail
: "${SONAR_TOKEN:?Export a SonarQube analysis token}"
: "${SONAR_HOST_URL:?Export the SonarQube URL}"
if [[ $# -ne 1 ]]; then echo "Usage: $0 /path/to/project" >&2; exit 2; fi
cd "$1"
[[ -f sonar-project.properties ]] || { echo "Missing sonar-project.properties" >&2; exit 2; }
sonar-scanner -Dsonar.qualitygate.wait=true -Dsonar.qualitygate.timeout=300
