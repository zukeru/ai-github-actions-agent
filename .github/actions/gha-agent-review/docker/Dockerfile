FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir boto3 botocore

WORKDIR /app
COPY gha_agent_review_agent /app/gha_agent_review_agent

CMD ["python", "-m", "gha_agent_review_agent.review_agent"]
