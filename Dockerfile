FROM python:3.11-slim

# psql/pg_isready 및 빌드 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client build-essential git \
    libpq-dev libxml2-dev libxslt1-dev \
    libldap2-dev libsasl2-dev libjpeg-dev zlib1g-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# pip 업그레이드 + 빌드 도구 (setuptools<71 keeps pkg_resources for cbor2)
RUN pip install --no-cache-dir --upgrade pip "setuptools<71" wheel cython

# Odoo 파이썬 의존성 (--no-build-isolation: 시스템 setuptools/cython 사용)
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

# 시작 스크립트 등록
COPY start-odoo.sh /usr/local/bin/start-odoo.sh
RUN chmod +x /usr/local/bin/start-odoo.sh

# Railway가 $PORT를 주입하므로 EXPOSE 불필요
CMD ["/usr/local/bin/start-odoo.sh"]
