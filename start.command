#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
    printf '%s\n' 'Не найден Docker. Установите Docker Desktop для Mac и повторите запуск.'
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    printf '%s\n' 'Запускаю Docker Desktop…'
    open -a Docker
    docker_ready=false
    for attempt in {1..30}; do
        if docker info >/dev/null 2>&1; then
            docker_ready=true
            break
        fi
        sleep 2
    done
    if [ "$docker_ready" != true ]; then
        printf '%s\n' 'Docker ещё не готов. Дождитесь запуска Docker Desktop и повторите.'
        exit 1
    fi
fi

docker compose up -d --build
for attempt in {1..30}; do
    if curl -fsS --max-time 2 'http://127.0.0.1:8088/api/health' >/dev/null 2>&1; then
        printf '%s\n' 'Comfy Vault готов: http://127.0.0.1:8088'
        open 'http://127.0.0.1:8088'
        exit 0
    fi
    sleep 2
done
printf '%s\n' 'Приложение не ответило. Посмотрите журнал командой: docker compose logs --tail=80'
exit 1
