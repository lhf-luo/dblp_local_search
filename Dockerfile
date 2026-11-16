FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DBLP_DATA_DIR=/data TZ=Asia/Shanghai
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
USER app
EXPOSE 40713
ENTRYPOINT ["dblp-local"]
CMD ["serve"]
