FROM python:3.11-slim

# psql/pg_isready 및 빌드 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client build-essential git \
    libpq-dev libxml2-dev libxslt1-dev \
    libldap2-dev libsasl2-dev libjpeg-dev zlib1g-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Odoo 파이썬 의존성
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir rjsmin==1.2.2

# 시작 스크립트 등록
COPY start-odoo.sh /usr/local/bin/start-odoo.sh
RUN chmod +x /usr/local/bin/start-odoo.sh

# Railway가 $PORT를 주입하므로 EXPOSE 불필요
CMD ["/usr/local/bin/start-odoo.sh"]
