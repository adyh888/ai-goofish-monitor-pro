# Stage 1: Build the Vue application
FROM node:22-alpine AS frontend-builder
WORKDIR /web-ui
COPY web-ui/package*.json ./
# 依赖源自动降级: 官方源失败则切国内镜像
RUN npm ci || npm ci --registry=https://registry.npmmirror.com
COPY web-ui/ .
RUN npm run build

# Stage 2: Build the python environment with dependencies
FROM python:3.11-slim-bookworm AS builder

# 设置环境变量以防止交互式提示
ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# 创建虚拟环境并安装 Python 运行时依赖
RUN python3 -m venv $VIRTUAL_ENV
COPY requirements-runtime.txt .
# pip 源自动降级: 清华源 → 阿里云源 → 官方源
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-runtime.txt \
    || pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements-runtime.txt \
    || pip install --no-cache-dir -i https://pypi.org/simple -r requirements-runtime.txt

# Stage 3: Create the final, lean image
FROM python:3.11-slim-bookworm

# apt 走阿里云 Debian 镜像(国内外均可用; 海外直连可 --build-arg APT_MIRROR=deb.debian.org 覆盖)
ARG APT_MIRROR=mirrors.aliyun.com

WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RUNNING_IN_DOCKER=true \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TINI_SUBREAPER=1 \
    TZ=Asia/Shanghai

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata \
        tini \
        libzbar0 \
    && (PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright playwright install --with-deps --no-shell chromium \
        || playwright install --with-deps --no-shell chromium) \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=frontend-builder /dist /app/dist

COPY src /app/src
COPY spider_v2.py /app/spider_v2.py
COPY prompts /app/prompts
COPY static /app/static
COPY config.json.example /app/config.json.example

RUN mkdir -p /app/data /app/state /app/logs /app/images /app/jsonl /app/price_history

EXPOSE 8000

USER root

ENTRYPOINT ["tini", "--"]

CMD ["python", "-m", "src.app"]
