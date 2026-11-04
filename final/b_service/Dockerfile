# APPROVED_EXTERNAL_B comparison service (approved / non-confidential samples only).
# Build from the repository's final/ folder:  docker build -f b_service/Dockerfile -t final-b .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY final_check /app/final_check
COPY b_service /app/b_service
# config.b.json is NOT baked into the image. Mount it or provide it as a secret file.
# FINAL_B_TOKEN can be provided as an environment variable instead of the config value.
ENV PYTHONUNBUFFERED=1
CMD ["python", "b_service/b_service.py", "--config", "/config/config.b.json"]
