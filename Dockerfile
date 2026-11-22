FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src src
COPY quality-policy.json .
RUN pip install --no-deps . && useradd --uid 10001 --create-home app && mkdir /app/artifacts && chown app /app/artifacts
USER app
ENTRYPOINT ["python", "-m", "quality_platform.gate"]
CMD ["--workspace", "/workspace", "--policy", "/app/quality-policy.json"]
