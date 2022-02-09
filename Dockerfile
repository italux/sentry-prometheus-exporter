FROM python:3.7-slim
LABEL maintainer="Italo Santos <italux.santos@gmail.com>"
LABEL description="Sentry Issues & Events Exporter"

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY helpers/ /app/helpers/
COPY libs/ /app/libs/
COPY exporter.py /app/


USER nobody

EXPOSE 9790
CMD ["python","/app/exporter.py"]