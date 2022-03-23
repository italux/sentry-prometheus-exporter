FROM python:3.7-slim
LABEL maintainer="Italo Santos <italux.santos@gmail.com>"
LABEL description="Sentry Issues & Events Exporter"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY helpers/ /app/helpers/
COPY libs/ /app/libs/
COPY exporter.py /app/

USER nobody

# The binding port was picked from the Default port allocations documentation:
# https://github.com/prometheus/prometheus/wiki/Default-port-allocations
EXPOSE 9790
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:9790", "exporter:app"]