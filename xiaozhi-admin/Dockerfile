FROM python:3.11-slim

WORKDIR /app
COPY admin.py .
COPY openai_patched.py .
COPY patch_descriptions.py .

RUN pip install --no-cache-dir aiohttp pyyaml docker

EXPOSE 8081

CMD ["python", "admin.py"]
