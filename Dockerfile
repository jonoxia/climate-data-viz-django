FROM python:3-alpine AS builder

WORKDIR /app

RUN python3 -m venv venv
ENV VIRTUAL_ENV=/app/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN apt-get update && apt-get install -y python3-distutils python3-pip

COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Stage 2
FROM python:3-alpine AS runner

ENV VIRTUAL_ENV=/app/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PORT=8000

WORKDIR /app

COPY --from=builder /app/venv venv
COPY django_framework django_framework
COPY geopportunity geopportunity

EXPOSE ${PORT}

CMD gunicorn --bind :${PORT} --workers 2 django_framework.wsgi
