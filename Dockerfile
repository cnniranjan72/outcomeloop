# OutcomeLoop controller image. Not required (run.sh runs natively), provided for a reproducible Linux run.
#   docker build -t outcomeloop .
#   docker run --rm --cpus 4 --memory 8g outcomeloop scripts/docker_scenario.sh public_01_dev
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
# the exact, audited versions (requirements.txt is the assignment's contract for run.sh)
RUN pip install -r requirements.lock.txt
COPY . .
RUN chmod +x run.sh scripts/*.sh
ENV OUTCOMELOOP_PYTHON=python
CMD ["bash", "-c", "echo 'usage: docker run ... outcomeloop ./run.sh <SIM_URL>   or   scripts/docker_scenario.sh <scenario>'"]
